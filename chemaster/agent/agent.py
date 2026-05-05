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

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from chemaster.agent.builtins import register_builtins
from chemaster.agent.context import ContextConfig, ContextManager
from chemaster.agent.llm_client import (
    BaseLLM,
    ContextOverflowError,
    LLMConfig,
    create_llm,
)
from chemaster.agent.tool_registry import BaseTool, ToolRegistry, ToolResult
from chemaster.agent.types import (
    AssistantMessage,
    Dialog,
    StepRecord,
    SystemMessage,
    TaskInstance,
    ToolCall,
    ToolMessage,
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
    recommend_callback: "RecommendCallback | None" = None  # v3.0: recommend mode handler
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

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def run(self, task: TaskInstance, on_step=None) -> Trajectory:
        """Execute one task end-to-end. Returns the trajectory."""
        self._initialize(task)
        assert self.trajectory is not None
        try:
            for turn in range(self.config.max_turns):
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
                    else:
                        self.trajectory.finish("completed")
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

    def continue_run(self, user_message: str, on_step=None) -> Trajectory:
        """Append a new user message to an existing dialog and continue."""
        if self.dialog is None:
            raise RuntimeError("continue_run called before run(); no active dialog.")
        self.dialog.add_message(UserMessage(content=user_message))
        # Reset step count for this turn but keep the dialog history.
        self._pending_ask_user = None
        # Reuse existing trajectory; mark it running again.
        if self.trajectory is None:
            self.trajectory = Trajectory()
        self.trajectory.status = "running"
        self.trajectory.finished_at = None
        for turn in range(self.config.max_turns):
            done = self._step()
            if on_step and self.trajectory.steps:
                on_step(self.trajectory.steps[-1], turn + 1, self.config.max_turns)
            if done:
                if self._pending_ask_user:
                    self.trajectory.finish("waiting_for_input", self._pending_ask_user)
                else:
                    self.trajectory.finish("completed")
                break
        else:
            self.trajectory.finish("failed", {"reason": "max_turns_exceeded"})
        self._persist_trajectory()
        return self.trajectory

    # ------------------------------------------------------------------
    # Loop body
    # ------------------------------------------------------------------

    def _step(self) -> bool:
        """One iteration: query LLM, dispatch tool calls. Returns True if done."""
        assert self.dialog is not None and self.trajectory is not None
        self._step_count += 1

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
                tool_msg = ToolMessage(
                    content="[finished]",
                    tool_call_id=tc.id,
                    name=tc.name,
                    meta={"finish_payload": tc.arguments},
                )
                self.dialog.add_message(tool_msg)
                step.tool_responses.append(tool_msg)
                # Stash on the trajectory for callers.
                self._finish_payload = tc.arguments
                break

            if tc.name == "ask_user":
                self._pending_ask_user = {
                    "questions": tc.arguments.get("questions", []),
                    "context": tc.arguments.get("context", ""),
                }
                tool_msg = ToolMessage(
                    content="[ask_user] Awaiting user response.",
                    tool_call_id=tc.id,
                    name=tc.name,
                    meta={
                        **self._pending_ask_user,
                        "decision_authority": "user-chemistry",
                    },
                )
                self.dialog.add_message(tool_msg)
                step.tool_responses.append(tool_msg)
                should_finish = True
                break

            if tc.name == "recommend":
                # v3.0 recommend mode: surface chemistry decision to the user.
                tool_msg = self._handle_recommend(tc)
                self.dialog.add_message(tool_msg)
                step.tool_responses.append(tool_msg)
                # If the user cancelled, treat as task termination.
                if tool_msg.meta and tool_msg.meta.get("recommend_status") == "cancel":
                    should_finish = True
                    break
                continue

            tool_msg = self._dispatch_tool(tc)
            self.dialog.add_message(tool_msg)
            step.tool_responses.append(tool_msg)

        self.trajectory.add_step(step)
        return should_finish

    # ------------------------------------------------------------------
    # Tool dispatch
    # ------------------------------------------------------------------

    def _dispatch_tool(self, tc: ToolCall) -> ToolMessage:
        tool = self.tools.get(tc.name)
        if tool is None:
            return ToolMessage(
                content=f"[error] Unknown tool: {tc.name}. Available: {self.tools.names()}",
                tool_call_id=tc.id,
                name=tc.name,
                is_error=True,
                meta={"error": "unknown_tool"},
            )

        # Confirmation gate (per-tool, only for destructive/long-running)
        if tool.needs_confirmation():
            cb = self.config.confirm_callback
            if cb is not None:
                reason = self._confirmation_reason(tool)
                approved = bool(cb(tc.name, tc.arguments, reason))
                self._record_confirmation(tc, reason, approved)
                if not approved:
                    return ToolMessage(
                        content=(
                            f"[user_declined] User declined to run {tc.name}. "
                            "Choose a different action or ask the user for clarification."
                        ),
                        tool_call_id=tc.id,
                        name=tc.name,
                        meta={"declined": True, "reason": reason},
                    )

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
        # v3.0: tag decision_authority on every tool message
        if tool.is_chemistry_decision:
            authority = "user-chemistry"
        elif tool.needs_confirmation():
            authority = "user-binary"
        else:
            authority = "agent"
        meta = {"decision_authority": authority}
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

    def _handle_recommend(self, tc: ToolCall) -> ToolMessage:
        """Process a `recommend` tool call by routing through the user.

        The recommend_callback receives the recommendation payload and returns:
            {"status": "accept" | "modify" | "cancel",
             "modified_value": "<user override>",   # iff status == "modify"
             "user_note": "<free-form note>"}        # optional

        If no callback is configured (script / test mode), default to accepting
        the agent's recommendation so the loop progresses.
        """
        payload = {
            "decision": tc.arguments.get("decision", ""),
            "recommendation": tc.arguments.get("recommendation", ""),
            "reasoning": tc.arguments.get("reasoning", ""),
            "alternatives": tc.arguments.get("alternatives", []),
            "tradeoffs": tc.arguments.get("tradeoffs", ""),
            "decision_class": tc.arguments.get("decision_class", "other"),
        }

        cb = self.config.recommend_callback
        if cb is None:
            # Auto-accept fallback so scripted tasks don't deadlock. The
            # trajectory still records this as a chemistry decision point.
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
                "decision_authority": "user-chemistry",
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
            {"accepted": 0, "modified": 0, "cancelled": 0, "log": []},
        )
        status = decision.get("status", "accept")
        record = {
            "tool": tc.name,
            "decision": payload.get("decision"),
            "recommendation": payload.get("recommendation"),
            "decision_class": payload.get("decision_class"),
            "status": status,
            "modified_value": decision.get("modified_value", ""),
            "user_note": decision.get("user_note", ""),
        }
        meta["recommendations"]["log"].append(record)
        if status == "accept":
            meta["recommendations"]["accepted"] += 1
        elif status == "modify":
            meta["recommendations"]["modified"] += 1
        else:
            meta["recommendations"]["cancelled"] += 1

        try:
            task_dir = self.config.runs_dir / self.trajectory.task_id
            task_dir.mkdir(parents=True, exist_ok=True)
            log_path = task_dir / "confirmations.jsonl"
            line = json.dumps(
                {"type": "recommend", **record},
                ensure_ascii=False,
                default=str,
            )
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            logger.exception("Failed to write recommend log")

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

        # Append to disk so the user can audit even after long runs.
        try:
            task_dir = self.config.runs_dir / self.trajectory.task_id
            task_dir.mkdir(parents=True, exist_ok=True)
            log_path = task_dir / "confirmations.jsonl"
            import json
            with log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
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
        # Ensure runs dir exists.
        self.config.runs_dir.mkdir(parents=True, exist_ok=True)
        (self.config.runs_dir / task.task_id).mkdir(parents=True, exist_ok=True)

    def _ensure_builtins(self) -> None:
        for name in ("finish", "ask_user", "think"):
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
