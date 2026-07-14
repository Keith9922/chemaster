"""BaseAgent + ChemAgent — the core tool-use loop.

Lifecycle (per `run(task)` call):

    1. _initialize: build SystemMessage + UserMessage, attach tool specs
    2. for turn in range(max_turns):
           dialog = context_manager.prepare_for_query(...)
           assistant_msg = llm.query(dialog)
           if assistant_msg has no tool_calls:
               nudge to use tools or finish
               continue
           for tool_call in assistant_msg.tool_calls:
               if tool_call.name == "finish":   → mark completed, break
               if tool_call.name == "ask_user": → pause, return waiting
               obs = dispatch(tool_call)
               append ToolMessage to dialog
       trajectory.save()

The Agent is *the* central component. Old Planner/Confirmation/Executor are
kept as compatibility shims (see planner.py / confirmation.py / executor.py)
so the existing H2O e2e test does not break.

Reference: EvoMaster's BaseAgent (evomaster/agent/agent.py).
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from chemaster.agent.builtins import register_builtins
from chemaster.agent.context import ContextConfig, ContextManager
from chemaster.agent.llm_client import (
    BaseLLM,
    ContextOverflowError,
    LLMConfig,
    create_llm,
)
from chemaster.agent.policy import Policy, load_policy
from chemaster.agent.tool_registry import BaseTool, ToolRegistry, ToolResult
from chemaster.agent.types import (
    AgentEvent,  # type: ignore  # union, for typing
    AssistantMessageEvent,
    ConfirmationRequiredEvent,
    Dialog,
    ErrorEvent,
    RunCompletedEvent,
    StepCompletedEvent,
    StepRecord,
    StepStartedEvent,
    SystemMessage,
    TaskInstance,
    ToolCall,
    ToolCompletedEvent,
    ToolMessage,
    ToolStartedEvent,
    Trajectory,
    UserMessage,
)

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# Config
# ══════════════════════════════════════════════════════════════════════════════


ConfirmCallback = Callable[[str, dict, str], bool]
"""Signature: (tool_name, args, reason) -> approved.

Returning False causes the Agent to abort that tool call (it is fed back as
an observation so the Agent can pick a different action)."""


AsyncConfirmCallback = Callable[[str, dict, str], Awaitable[bool]]
"""Async variant of ConfirmCallback for use with `run_streaming`.

The Web UI / WebSocket layer needs to suspend on user input without blocking
the event loop, so it provides this instead of (or in addition to) the sync
callback.  When `run_streaming` is invoked, the agent prefers
`async_confirm_callback`; it falls back to `confirm_callback` (called inline)
if only the sync version is supplied."""


# v3.0: callback signature for the recommend mode.
# Input: a payload describing the chemistry decision (decision, recommendation,
#        reasoning, alternatives, tradeoffs, decision_class).
# Output: dict with at least ``status`` ∈ {"accept", "modify", "cancel"}, and
#         optionally ``modified_value`` (when status == "modify") or
#         ``user_note`` (free-form context the agent should respect).
RecommendCallback = Callable[[dict], dict]


@dataclass
class AgentConfig:
    max_turns: int = 30                   # safe default; H2O finishes in 3-5
    runs_dir: Path = Path("./runs")
    context: ContextConfig = field(default_factory=ContextConfig)
    enable_builtins: bool = True
    enabled_tools: list[str] | None = None      # None = all registered tools exposed
    confirm_callback: ConfirmCallback | None = None   # None = auto-approve
    async_confirm_callback: AsyncConfirmCallback | None = None  # used by run_streaming
    recommend_callback: RecommendCallback | None = None  # v3.0: recommend mode handler
    policy: Policy | None = None   # None = lazy-load ~/.chemaster/policy.yaml
    should_abort: Callable[[], bool] | None = None  # 协作式取消（每轮询问一次）
    max_tool_observation_chars: int = 30_000
    finish_on_no_tool_calls: bool = False        # treat plain text as completion?

    def __post_init__(self) -> None:
        # Coerce string paths to Path so callers can pass tempfile.TemporaryDirectory
        # results, str literals, etc.
        if not isinstance(self.runs_dir, Path):
            self.runs_dir = Path(self.runs_dir)


# ══════════════════════════════════════════════════════════════════════════════
# Agent
# ══════════════════════════════════════════════════════════════════════════════


class BaseAgent:
    """The tool-use loop.

    Subclasses override `_get_system_prompt` and `_get_user_prompt` to inject
    domain knowledge.
    """

    VERSION: str = "0.2.0"

    def __init__(
        self,
        llm: BaseLLM,
        tools: ToolRegistry,
        config: AgentConfig | None = None,
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.config = config or AgentConfig()
        if self.config.enable_builtins:
            self._ensure_builtins()
        self.context_manager = ContextManager(self.config.context)
        self.dialog: Dialog | None = None
        self.trajectory: Trajectory | None = None
        self._step_count = 0
        self._pending_ask_user: dict | None = None
        self._finish_payload: dict | None = None
        self._recommend_cancelled = False
        self._policy: Policy | None = self.config.policy

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def run(self, task: TaskInstance, on_step=None) -> Trajectory:
        """Execute one task end-to-end. Returns the trajectory."""
        self._initialize(task)
        return self._run_loop(on_step)

    def continue_run(self, user_message: str, on_step=None) -> Trajectory:
        """Append a new user message to an existing dialog and continue."""
        if self.dialog is None:
            raise RuntimeError("continue_run called before run(); no active dialog.")
        self.dialog.add_message(UserMessage(content=user_message))
        # Reset the pause flag for this turn but keep the dialog history.
        self._pending_ask_user = None
        # Reuse existing trajectory; mark it running again.
        if self.trajectory is None:
            self.trajectory = Trajectory()
        self.trajectory.status = "running"
        self.trajectory.finished_at = None
        return self._run_loop(on_step)

    def _run_loop(self, on_step=None) -> Trajectory:
        """Shared sync driver behind `run` and `continue_run`."""
        assert self.trajectory is not None
        try:
            for turn in range(self.config.max_turns):
                if self.config.should_abort and self.config.should_abort():
                    # 协作式取消：Web 的取消按钮此前只是前端停止轮询，
                    # 后端线程照跑到 max_turns —— 现在真的停。
                    logger.info("Abort requested — cancelling task cleanly")
                    self.trajectory.finish("cancelled",
                                           {"reason": "user_cancelled"})
                    break
                logger.info("─" * 60)
                logger.info("Step %d / %d", turn + 1, self.config.max_turns)
                done = self._step()
                if on_step and self.trajectory.steps:
                    try:
                        on_step(self.trajectory.steps[-1], turn + 1, self.config.max_turns)
                    except Exception as cb_exc:
                        logger.warning("on_step callback raised: %s", cb_exc)
                if done:
                    if self._pending_ask_user:
                        self.trajectory.finish("waiting_for_input", self._pending_ask_user)
                    elif self._recommend_cancelled:
                        self.trajectory.finish(
                            "cancelled", {"reason": "user_cancelled_recommend"})
                    else:
                        self.trajectory.finish("completed", self._finish_payload)
                    break
            else:
                logger.warning("Reached max_turns=%d without finishing", self.config.max_turns)
                self.trajectory.finish("failed", {"reason": "max_turns_exceeded"})
        except Exception as exc:
            logger.exception("Agent loop raised")
            self.trajectory.finish("failed", {"reason": str(exc)})
            self._persist_trajectory()
            raise

        self._persist_trajectory()
        return self.trajectory

    # ------------------------------------------------------------------
    # Streaming loop  (used by `chemaster web` and live CLI rendering)
    # ------------------------------------------------------------------

    async def run_streaming(
        self,
        task: TaskInstance,
    ) -> AsyncIterator[AgentEvent]:
        """Execute one task and yield AgentEvents as they happen.

        This is the source-of-truth for browser clients (FastAPI WebSocket
        consumer) and for the new live-rendering CLI path.  It does NOT
        replace the sync `run()` — that codepath is preserved unchanged so
        the existing 172-test suite stays green.

        Confirmation flow: when a destructive / long-running tool fires, a
        ConfirmationRequiredEvent is yielded *before* the tool runs.  The
        consumer must resolve `config.async_confirm_callback` (or fall back
        to `config.confirm_callback`) before the tool dispatches.

        Errors: a non-fatal step-level error becomes an ErrorEvent.  A fatal
        (the loop itself crashes) marks the trajectory failed and yields a
        terminal RunCompletedEvent with status="failed".
        """
        self._initialize(task)
        assert self.trajectory is not None
        try:
            for turn in range(self.config.max_turns):
                if self.config.should_abort and self.config.should_abort():
                    logger.info("Abort requested — cancelling streaming task")
                    self.trajectory.finish("cancelled",
                                           {"reason": "user_cancelled"})
                    break
                step_id = turn + 1
                yield StepStartedEvent(step_id=step_id)
                logger.info("─" * 60)
                logger.info("Step %d / %d", step_id, self.config.max_turns)

                done = False
                async for event in self._step_streaming(step_id):
                    yield event
                    if isinstance(event, StepCompletedEvent) and event.finish_signaled:
                        done = True

                if done:
                    if self._pending_ask_user:
                        self.trajectory.finish("waiting_for_input", self._pending_ask_user)
                    elif self._recommend_cancelled:
                        self.trajectory.finish(
                            "cancelled", {"reason": "user_cancelled_recommend"})
                    else:
                        self.trajectory.finish("completed", self._finish_payload)
                    break
            else:
                logger.warning("Reached max_turns=%d without finishing", self.config.max_turns)
                self.trajectory.finish("failed", {"reason": "max_turns_exceeded"})
        except Exception as exc:
            logger.exception("Streaming agent loop raised")
            self.trajectory.finish("failed", {"reason": str(exc)})
            yield ErrorEvent(
                step_id=self._step_count,
                error_type=type(exc).__name__,
                message=str(exc),
            )
        finally:
            self._persist_trajectory()

        # finish_payload semantics:
        #   - status="completed"          → args of the finish tool call
        #   - status="waiting_for_input"  → pending ask_user payload (mirrors trajectory)
        #   - status="failed"             → leave None; surface "reason" instead
        finish_payload: dict[str, Any] | None
        reason: str | None
        if self.trajectory.status == "failed":
            finish_payload = None
            reason = (self.trajectory.finish_payload or {}).get("reason")
        else:
            finish_payload = self._finish_payload or self.trajectory.finish_payload
            reason = None
        yield RunCompletedEvent(
            task_id=self.trajectory.task_id,
            status=self.trajectory.status,
            finish_payload=finish_payload,
            reason=reason,
        )

    async def _step_streaming(self, step_id: int) -> AsyncIterator[AgentEvent]:
        """One iteration of the loop, emitting events at every transition.

        Message shapes, decision_authority tags and audit records are shared
        with the sync `_step` via the `_*_message` helpers — semantics live
        there, not here.
        """
        assert self.dialog is not None and self.trajectory is not None
        self._step_count += 1

        assistant = self._query_assistant()
        step = StepRecord(step_id=self._step_count, assistant_message=assistant)

        yield AssistantMessageEvent(
            step_id=step_id,
            text=assistant.content or "",
            tool_calls=[tc.to_dict() for tc in assistant.tool_calls],
            meta=dict(assistant.meta or {}),
        )

        # Plain text without tool call.
        if not assistant.tool_calls:
            if self.config.finish_on_no_tool_calls:
                self.trajectory.add_step(step)
                yield StepCompletedEvent(step_id=step_id, finish_signaled=True)
                return
            self._nudge_no_tool_call()
            self.trajectory.add_step(step)
            yield StepCompletedEvent(step_id=step_id, finish_signaled=False)
            return

        should_finish = False
        for tc in assistant.tool_calls:
            # finish / ask_user are control-flow built-ins, never dispatched.
            if tc.name == "finish":
                should_finish = True
                tool_msg = self._finish_message(tc)
                self._append_tool_message(step, tool_msg)
                yield ToolCompletedEvent(
                    step_id=step_id,
                    tool_call_id=tc.id,
                    tool_name=tc.name,
                    ok=True,
                    is_error=False,
                    observation=tool_msg.content,
                    data={"finish_payload": tc.arguments},
                )
                break

            if tc.name == "ask_user":
                tool_msg = self._ask_user_message(tc)
                self._append_tool_message(step, tool_msg)
                should_finish = True
                yield ToolCompletedEvent(
                    step_id=step_id,
                    tool_call_id=tc.id,
                    tool_name=tc.name,
                    ok=True,
                    is_error=False,
                    observation=tool_msg.content,
                    data=dict(self._pending_ask_user or {}),
                )
                break

            if tc.name == "recommend":
                # Chemistry decision point — same handler as the sync path.
                # The callback may block on user input, so run it off-loop.
                tool_msg = await asyncio.to_thread(self._handle_recommend, tc)
                self._append_tool_message(step, tool_msg)
                status = (tool_msg.meta or {}).get("recommend_status")
                yield ToolCompletedEvent(
                    step_id=step_id,
                    tool_call_id=tc.id,
                    tool_name=tc.name,
                    ok=status != "cancel",
                    is_error=False,
                    observation=tool_msg.content,
                    data=dict(tool_msg.meta or {}),
                )
                if status == "cancel":
                    self._recommend_cancelled = True
                    should_finish = True
                    break
                if status == "escalated":
                    should_finish = True
                    break
                continue

            # Real tool — emit confirmation/started/completed events.  The
            # dispatcher appends the ToolMessage itself, so event emission
            # and dialog bookkeeping cannot drift apart.
            async for event in self._dispatch_tool_streaming(tc, step_id, step):
                yield event

        self.trajectory.add_step(step)
        yield StepCompletedEvent(step_id=step_id, finish_signaled=should_finish)

    async def _dispatch_tool_streaming(
        self,
        tc: ToolCall,
        step_id: int,
        step: StepRecord,
    ) -> AsyncIterator[AgentEvent]:
        """Dispatch one tool call, yielding (Confirmation?, Started, Completed).

        Builds the exact same ToolMessages as the sync `_dispatch_tool` (via
        the shared helpers) and appends them to dialog + step itself.
        """
        tool = self.tools.get(tc.name)
        if tool is None:
            tool_msg = self._unknown_tool_message(tc)
            self._append_tool_message(step, tool_msg)
            yield ToolCompletedEvent(
                step_id=step_id,
                tool_call_id=tc.id,
                tool_name=tc.name,
                ok=False,
                is_error=True,
                observation=tool_msg.content,
                data={"error": "unknown_tool"},
            )
            return

        if tool.needs_confirmation():
            reason = self._confirmation_reason(tool)
            yield ConfirmationRequiredEvent(
                step_id=step_id,
                tool_call_id=tc.id,
                tool_name=tc.name,
                arguments=dict(tc.arguments),
                reason=reason,
            )
            approved, decided = await self._await_confirmation(tc, reason)
            if decided:
                self._record_confirmation(tc, reason, approved)
            if not approved:
                tool_msg = self._declined_message(tc, reason)
                self._append_tool_message(step, tool_msg)
                yield ToolCompletedEvent(
                    step_id=step_id,
                    tool_call_id=tc.id,
                    tool_name=tc.name,
                    ok=False,
                    is_error=False,
                    declined=True,
                    observation=tool_msg.content,
                    data={"declined": True, "reason": reason},
                )
                return

        yield ToolStartedEvent(
            step_id=step_id,
            tool_call_id=tc.id,
            tool_name=tc.name,
            arguments=dict(tc.arguments),
        )

        # Run in a worker thread so a slow engine call does not block the
        # event loop that is streaming these events out.
        result, observation = await asyncio.to_thread(self._execute_tool, tool, tc)
        tool_msg = self._tool_message(tc, tool, result, observation)
        self._append_tool_message(step, tool_msg)
        yield ToolCompletedEvent(
            step_id=step_id,
            tool_call_id=tc.id,
            tool_name=tc.name,
            ok=result.ok,
            is_error=result.is_error or not result.ok,
            observation=observation,
            data=result.data if result.data else None,
        )

    async def _await_confirmation(self, tc: ToolCall, reason: str) -> tuple[bool, bool]:
        """Resolve a confirmation. Returns (approved, decided_by_callback).

        decided_by_callback=False means no callback was configured and the
        call was auto-approved — matching the sync path, pure auto-approvals
        are not written to the audit log.
        """
        async_cb = self.config.async_confirm_callback
        if async_cb is not None:
            res = async_cb(tc.name, dict(tc.arguments), reason)
            if inspect.isawaitable(res):
                return bool(await res), True
            return bool(res), True
        sync_cb = self.config.confirm_callback
        if sync_cb is not None:
            # Run sync callback in a thread so a slow blocking prompt does
            # not stall the event loop.
            approved = await asyncio.to_thread(
                sync_cb, tc.name, dict(tc.arguments), reason
            )
            return bool(approved), True
        # No callback configured → auto-approve (legacy default).
        return True, False

    # ------------------------------------------------------------------
    # Loop body
    # ------------------------------------------------------------------

    def _step(self) -> bool:
        """One iteration: query LLM, dispatch tool calls. Returns True if done."""
        assert self.dialog is not None and self.trajectory is not None
        self._step_count += 1

        assistant = self._query_assistant()
        step = StepRecord(step_id=self._step_count, assistant_message=assistant)

        # No tool calls
        if not assistant.tool_calls:
            if self.config.finish_on_no_tool_calls:
                self.trajectory.add_step(step)
                return True
            self._nudge_no_tool_call()
            self.trajectory.add_step(step)
            return False

        should_finish = False
        for tc in assistant.tool_calls:
            if tc.name == "finish":
                should_finish = True
                self._append_tool_message(step, self._finish_message(tc))
                break

            if tc.name == "ask_user":
                self._append_tool_message(step, self._ask_user_message(tc))
                should_finish = True
                break

            if tc.name == "recommend":
                # v3.0 recommend mode: surface chemistry decision to the user.
                tool_msg = self._handle_recommend(tc)
                self._append_tool_message(step, tool_msg)
                # cancel → task termination; escalated (L3, no channel) →
                # pause via pending ask_user set by _handle_recommend.
                rec_status = (tool_msg.meta or {}).get("recommend_status")
                if rec_status == "cancel":
                    self._recommend_cancelled = True
                    should_finish = True
                    break
                if rec_status == "escalated":
                    should_finish = True
                    break
                continue

            self._append_tool_message(step, self._dispatch_tool(tc))

        self.trajectory.add_step(step)
        return should_finish

    # ------------------------------------------------------------------
    # Tool dispatch
    # ------------------------------------------------------------------

    def _dispatch_tool(self, tc: ToolCall) -> ToolMessage:
        tool = self.tools.get(tc.name)
        if tool is None:
            return self._unknown_tool_message(tc)

        # Confirmation gate (per-tool, only for destructive/long-running).
        # No callback configured → auto-approve without an audit record,
        # mirroring `_await_confirmation` on the streaming path.
        if tool.needs_confirmation():
            cb = self.config.confirm_callback
            if cb is not None:
                reason = self._confirmation_reason(tool)
                approved = bool(cb(tc.name, tc.arguments, reason))
                self._record_confirmation(tc, reason, approved)
                if not approved:
                    return self._declined_message(tc, reason)

        result, observation = self._execute_tool(tool, tc)
        return self._tool_message(tc, tool, result, observation)

    # ------------------------------------------------------------------
    # Shared step building blocks (single source of truth for both paths)
    # ------------------------------------------------------------------

    def _query_assistant(self):
        """Query the LLM with context compaction, overflow retry and usage
        bookkeeping, then append the assistant message to the dialog."""
        assert self.dialog is not None
        dialog_for_query, compacted = self.context_manager.prepare_for_query(self.dialog)
        if compacted:
            self.dialog = dialog_for_query
            self.context_manager.reset_prompt_tokens()

        try:
            assistant = self.llm.query(dialog_for_query)
        except ContextOverflowError:
            logger.warning("Context overflow, emergency truncate + retry")
            self.dialog = self.context_manager.truncate(self.dialog)
            self.context_manager.reset_prompt_tokens()
            assistant = self.llm.query(self.dialog)

        usage = (assistant.meta or {}).get("usage")
        if usage:
            self.context_manager.update_usage(usage)
            if self.context_manager.is_overflow(usage):
                self.dialog = self.context_manager.truncate(self.dialog)
                self.context_manager.reset_prompt_tokens()

        self.dialog.add_message(assistant)
        return assistant

    def _append_tool_message(self, step: StepRecord, tool_msg: ToolMessage) -> None:
        assert self.dialog is not None
        self.dialog.add_message(tool_msg)
        step.tool_responses.append(tool_msg)

    def _finish_message(self, tc: ToolCall) -> ToolMessage:
        # Stash on the agent for callers; `_run_loop` / `run_streaming`
        # write it back to `trajectory.finish_payload`.
        self._finish_payload = tc.arguments
        return ToolMessage(
            content="[finished]",
            tool_call_id=tc.id,
            name=tc.name,
            meta={"finish_payload": tc.arguments},
        )

    def _ask_user_message(self, tc: ToolCall) -> ToolMessage:
        self._pending_ask_user = {
            "questions": tc.arguments.get("questions", []),
            "context": tc.arguments.get("context", ""),
        }
        return ToolMessage(
            content="[ask_user] Awaiting user response.",
            tool_call_id=tc.id,
            name=tc.name,
            meta={
                **self._pending_ask_user,
                "decision_authority": "user-chemistry",
            },
        )

    def _unknown_tool_message(self, tc: ToolCall) -> ToolMessage:
        return ToolMessage(
            content=f"[error] Unknown tool: {tc.name}. Available: {self.tools.names()}",
            tool_call_id=tc.id,
            name=tc.name,
            is_error=True,
            meta={"error": "unknown_tool"},
        )

    def _declined_message(self, tc: ToolCall, reason: str) -> ToolMessage:
        return ToolMessage(
            content=(
                f"[user_declined] User declined to run {tc.name}. "
                "Choose a different action or ask the user for clarification."
            ),
            tool_call_id=tc.id,
            name=tc.name,
            meta={"declined": True, "reason": reason},
        )

    def _execute_tool(self, tool: BaseTool, tc: ToolCall) -> tuple[ToolResult, str]:
        """Run the tool, mapping exceptions to error results and truncating
        oversized observations."""
        try:
            result = tool.run(**tc.arguments)
        except TypeError as exc:
            result = ToolResult(
                ok=False,
                observation=f"[error] Tool {tc.name} called with invalid arguments: {exc}",
                data={"error_code": "INVALID_ARGS", "details": str(exc)},
                is_error=True,
            )
        except Exception as exc:
            logger.exception("Tool %s raised", tc.name)
            result = ToolResult(
                ok=False,
                observation=f"[error] Tool {tc.name} raised: {type(exc).__name__}: {exc}",
                data={"error_code": "TOOL_EXCEPTION", "details": str(exc)},
                is_error=True,
            )
        observation = result.observation
        if len(observation) > self.config.max_tool_observation_chars:
            half = self.config.max_tool_observation_chars // 2
            observation = (
                observation[:half]
                + "\n... [truncated] ...\n"
                + observation[-half:]
            )
        return result, observation

    def _authority_for(self, tool: BaseTool) -> str:
        """v3.0 decision_authority tag: who owned this step."""
        if tool.is_chemistry_decision:
            return "user-chemistry"
        if tool.needs_confirmation():
            return "user-binary"
        return "agent"

    def _tool_message(
        self,
        tc: ToolCall,
        tool: BaseTool,
        result: ToolResult,
        observation: str,
    ) -> ToolMessage:
        meta: dict[str, Any] = {"decision_authority": self._authority_for(tool)}
        if result.data:
            meta["data"] = result.data
        return ToolMessage(
            content=observation,
            tool_call_id=tc.id,
            name=tc.name,
            is_error=result.is_error or not result.ok,
            meta=meta,
        )

    # ------------------------------------------------------------------
    # Recommend mode (v3.0)
    # ------------------------------------------------------------------

    def _get_policy(self) -> Policy:
        """Resolve the permission policy (lazy: ~/.chemaster/policy.yaml)."""
        if self._policy is None:
            self._policy = load_policy()
        return self._policy

    def _handle_recommend(self, tc: ToolCall) -> ToolMessage:
        """Process a `recommend` tool call by routing through the user.

        v3.0 权限分级（~/.chemaster/policy.yaml）在这里落地执行：

        - **L1**（用户已把该 decision_class 降级为自主）→ 不打扰用户，
          静默接受推荐；trajectory / confirmations.jsonl 照记，
          decision_authority 记为 ``agent``。
        - **L2**（默认）→ recommend_callback 呈卡片，用户
          accept / modify / cancel；无 callback（脚本模式）时自动接受。
        - **L3** → 必须用户决断：有 callback 时同样走卡片（由用户拍板）；
          **无 callback 时不允许自动接受** —— 升级为 pending ask_user，
          任务转为 waiting_for_input 等待用户。

        The recommend_callback receives the recommendation payload (incl. the
        resolved ``level``) and returns:
            {"status": "accept" | "modify" | "cancel",
             "modified_value": "<user override>",   # iff status == "modify"
             "user_note": "<free-form note>"}        # optional
        """
        payload = {
            "decision": tc.arguments.get("decision", ""),
            "recommendation": tc.arguments.get("recommendation", ""),
            "reasoning": tc.arguments.get("reasoning", ""),
            "alternatives": tc.arguments.get("alternatives", []),
            "tradeoffs": tc.arguments.get("tradeoffs", ""),
            "decision_class": tc.arguments.get("decision_class", "other"),
        }
        level = self._get_policy().level_for_decision(payload["decision_class"])
        payload["level"] = level

        cb = self.config.recommend_callback
        authority = "user-chemistry"

        if level == "L1":
            # Policy demoted this class to autonomous — suppress the prompt,
            # keep the full audit trail.
            decision_payload = {
                "status": "accept",
                "modified_value": "",
                "user_note": (
                    f"(auto-accepted: decision_class "
                    f"'{payload['decision_class']}' demoted to L1 by policy)"
                ),
            }
            authority = "agent"
        elif cb is None:
            if level == "L3":
                # L3 without an interactive channel: never assume — escalate
                # to ask_user and pause the task.
                self._pending_ask_user = {
                    "questions": [
                        f"[L3 decision: {payload['decision_class']}] "
                        f"{payload['decision']} — agent recommends: "
                        f"{payload['recommendation']}. Approve or override?"
                    ],
                    "context": payload["reasoning"],
                }
                decision_payload = {"status": "escalated", "user_note": ""}
                self._record_recommend(tc, payload, decision_payload)
                return ToolMessage(
                    content=(
                        "[recommend:escalated] decision_class "
                        f"'{payload['decision_class']}' is L3 (must ask user) "
                        "and no recommend channel is available — escalating "
                        "to ask_user."
                    ),
                    tool_call_id=tc.id,
                    name=tc.name,
                    meta={
                        "recommend_payload": payload,
                        "recommend_decision": decision_payload,
                        "recommend_status": "escalated",
                        "decision_authority": "user-chemistry",
                        "escalation": True,
                    },
                )
            # L2 script mode: auto-accept so scripted tasks don't deadlock.
            # The trajectory still records this as a chemistry decision point.
            decision_payload = {
                "status": "accept",
                "modified_value": "",
                "user_note": "(auto-accepted: no recommend_callback configured)",
            }
        else:
            try:
                decision_payload = cb(payload) or {"status": "accept"}
            except Exception as exc:
                logger.exception("recommend_callback raised on %s", payload.get("decision"))
                decision_payload = {
                    "status": "cancel",
                    "user_note": f"recommend_callback error: {exc}",
                }

        status = decision_payload.get("status", "accept")
        modified = decision_payload.get("modified_value", "")
        user_note = decision_payload.get("user_note", "")

        # Build the observation the LLM sees.
        if status == "accept":
            obs = (
                f"[recommend:accepted] User accepted: {payload['recommendation']}. "
                f"Proceed with this choice."
            )
        elif status == "modify":
            obs = (
                f"[recommend:modified] User overrode the recommendation. "
                f"Use this value instead: {modified}. "
                f"User note: {user_note}"
            )
        else:  # cancel
            obs = (
                f"[recommend:cancel] User cancelled the task at this decision "
                f"point. Note: {user_note}"
            )

        # Record this as a chemistry decision in confirmations.jsonl.
        self._record_recommend(tc, payload, decision_payload)

        return ToolMessage(
            content=obs,
            tool_call_id=tc.id,
            name=tc.name,
            meta={
                "recommend_payload": payload,
                "recommend_decision": decision_payload,
                "recommend_status": status,
                "decision_authority": authority,
            },
        )

    def _record_recommend(
        self,
        tc: ToolCall,
        payload: dict,
        decision: dict,
    ) -> None:
        """Log every recommend interaction to confirmations.jsonl + trajectory meta."""
        if self.trajectory is None:
            return
        meta = self.trajectory.meta
        meta.setdefault(
            "recommendations",
            {"accepted": 0, "modified": 0, "cancelled": 0, "escalated": 0, "log": []},
        )
        status = decision.get("status", "accept")
        record = {
            "tool": tc.name,
            "decision": payload.get("decision"),
            "recommendation": payload.get("recommendation"),
            "decision_class": payload.get("decision_class"),
            "level": payload.get("level", ""),
            "status": status,
            "modified_value": decision.get("modified_value", ""),
            "user_note": decision.get("user_note", ""),
        }
        meta["recommendations"]["log"].append(record)
        if status == "accept":
            meta["recommendations"]["accepted"] += 1
        elif status == "modify":
            meta["recommendations"]["modified"] += 1
        elif status == "escalated":
            meta["recommendations"].setdefault("escalated", 0)
            meta["recommendations"]["escalated"] += 1
        else:
            meta["recommendations"]["cancelled"] += 1

        self._append_audit_line({"type": "recommend", **record})

    @staticmethod
    def _confirmation_reason(tool: BaseTool) -> str:
        reasons = []
        if tool.is_destructive:
            reasons.append("destructive (writes external state)")
        if tool.is_long_running:
            reasons.append("long-running (>30 s expected)")
        return ", ".join(reasons) or "requires confirmation"

    def _record_confirmation(self, tc: ToolCall, reason: str, approved: bool) -> None:
        """Log every confirmation prompt to runs/<task_id>/confirmations.jsonl."""
        if self.trajectory is None:
            return
        meta = self.trajectory.meta
        meta.setdefault("confirmations", {"approved": 0, "declined": 0, "log": []})
        record = {
            "tool": tc.name,
            "args": tc.arguments,
            "reason": reason,
            "approved": approved,
        }
        meta["confirmations"]["log"].append(record)
        meta["confirmations"]["approved" if approved else "declined"] += 1
        self._append_audit_line(record)

    def _append_audit_line(self, record: dict) -> None:
        """Append one JSON line to runs/<task_id>/confirmations.jsonl so the
        user can audit decisions even after long runs."""
        if self.trajectory is None:
            return
        try:
            task_dir = self.config.runs_dir / self.trajectory.task_id
            task_dir.mkdir(parents=True, exist_ok=True)
            log_path = task_dir / "confirmations.jsonl"
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except Exception as exc:
            logger.warning("Failed to persist confirmation log: %s", exc)

    # ------------------------------------------------------------------
    # No-tool-call handling
    # ------------------------------------------------------------------

    def _nudge_no_tool_call(self) -> None:
        """Append a nudge so the LLM either calls tools or finishes."""
        assert self.dialog is not None
        self.dialog.add_message(UserMessage(content=(
            "Continue working on the task. Either call tools to advance the "
            "calculation, or call the `finish` tool with a summary if you are "
            "fully done. Do not produce free-form text without a tool call."
        )))

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def _initialize(self, task: TaskInstance) -> None:
        self.trajectory = Trajectory(
            task_id=task.task_id,
            meta={"agent_version": self.VERSION, "task_type": task.task_type},
        )
        sys_prompt = self._get_system_prompt()
        user_prompt = self._get_user_prompt(task)
        self.dialog = Dialog(
            messages=[SystemMessage(content=sys_prompt), UserMessage(content=user_prompt)],
            tools=self.tools.specs(self.config.enabled_tools),
        )
        self._step_count = 0
        self._pending_ask_user = None
        self._finish_payload = None
        self._recommend_cancelled = False
        # Ensure runs dir exists.
        self.config.runs_dir.mkdir(parents=True, exist_ok=True)
        task_dir = self.config.runs_dir / task.task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        # 引擎日志（psi4 等）归档到 runs/<task>/engine_logs/，恢复 §5.6 的
        # 复现承诺（psi4 会话隔离后日志曾只落在临时目录）。进程级 env —
        # 同进程内 MCP 引擎调用本就是单飞的（psi4 全局状态），可接受。
        os.environ["CHEMASTER_ENGINE_LOG_DIR"] = str(task_dir / "engine_logs")

    def _ensure_builtins(self) -> None:
        for name in ("finish", "ask_user", "think", "recommend"):
            if not self.tools.has(name):
                register_builtins(self.tools)
                return

    def _persist_trajectory(self) -> None:
        if self.trajectory is None:
            return
        task_dir = self.config.runs_dir / self.trajectory.task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        trajectory_path = task_dir / "trajectory.json"
        try:
            self.trajectory.save(trajectory_path)
        except Exception as exc:
            logger.warning("Failed to persist trajectory: %s", exc)

    # ------------------------------------------------------------------
    # Convenience accessors
    # ------------------------------------------------------------------

    @property
    def finish_payload(self) -> dict | None:
        return getattr(self, "_finish_payload", None)

    # Subclasses must override these.
    def _get_system_prompt(self) -> str:
        return "You are a helpful assistant."

    def _get_user_prompt(self, task: TaskInstance) -> str:
        return task.description


# ══════════════════════════════════════════════════════════════════════════════
# ChemAgent — domain specialization
# ══════════════════════════════════════════════════════════════════════════════


class ChemAgent(BaseAgent):
    """Computational-chemistry specialization of BaseAgent.

    Loads the chemistry expert prompt from `system_prompt.md` (next to this
    file) and shapes the user prompt with task metadata.
    """

    _SYSTEM_PROMPT_FILENAME = "system_prompt.md"

    def __init__(
        self,
        llm: BaseLLM | None = None,
        tools: ToolRegistry | None = None,
        config: AgentConfig | None = None,
        system_prompt_override: str | None = None,
    ) -> None:
        if llm is None:
            llm = create_llm(LLMConfig(provider="mock"))
        if tools is None:
            tools = ToolRegistry()
        super().__init__(llm=llm, tools=tools, config=config)
        self._system_prompt_override = system_prompt_override

    def _get_system_prompt(self) -> str:
        if self._system_prompt_override is not None:
            return self._system_prompt_override
        path = Path(__file__).parent / self._SYSTEM_PROMPT_FILENAME
        if not path.exists():
            logger.warning("System prompt file missing: %s — using minimal default", path)
            return self._minimal_default_prompt()
        return path.read_text(encoding="utf-8")

    def _get_user_prompt(self, task: TaskInstance) -> str:
        parts = [
            f"Task: {task.description}",
        ]
        if task.input_data:
            parts.append(f"\nAdditional input:\n{task.input_data}")
        return "\n".join(parts)

    @staticmethod
    def _minimal_default_prompt() -> str:
        return (
            "You are ChemMaster, an autonomous computational-chemistry agent. "
            "Use the available tools to plan and execute the user's calculation. "
            "Call `finish` with a summary when done."
        )


# ══════════════════════════════════════════════════════════════════════════════
# Factory
# ══════════════════════════════════════════════════════════════════════════════


def build_default_chem_agent(
    llm: BaseLLM | None = None,
    runs_dir: str | Path = "./runs",
    confirm_callback: ConfirmCallback | None = None,
    enabled_tools: list[str] | None = None,
) -> ChemAgent:
    """Construct a ChemAgent with all built-ins + every available MCP tool wired."""
    from chemaster.agent.tool_loader import build_default_registry

    tools = build_default_registry()
    config = AgentConfig(
        runs_dir=Path(runs_dir),
        confirm_callback=confirm_callback,
        enabled_tools=enabled_tools,
    )
    return ChemAgent(llm=llm, tools=tools, config=config)


__all__ = [
    "AgentConfig",
    "BaseAgent",
    "ChemAgent",
    "ConfirmCallback",
    "build_default_chem_agent",
]
