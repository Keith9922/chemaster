"""BaseChemAgent —— ChemMaster 的 Agent 执行核心。

参考 EvoMaster BaseAgent，结合计算化学的 Plan-Confirm-Execute 三段式：

执行模式：
1. **对话模式**（chat_mode=True）：
   LLM 自由对话，可调用 use_skill 等工具获取知识，
   当 LLM 认为应该启动计算时调用 plan_and_execute 工具。

2. **直接执行模式**（chat_mode=False）：
   传入已有 Plan，直接走 Confirmation → Execute 流程。

核心特性（来自 EvoMaster）：
- _step()：单步执行循环（query → tool_calls → record）
- continue_run()：多轮对话支持
- ask_user 暂停机制：LLM 不确定时暂停等用户输入
- Trajectory 逐步记录：每步写 JSON，3 个月后可复现
- Context 自动截断：防止长任务撑爆 context window

ChemMaster 专属扩展：
- Plan-Confirm 三段式集成（LLM → Plan → 用户确认 → Executor）
- Skill 注入：system prompt 包含所有 Skill 的 Level 1 摘要
- 单位安全：所有计算数值走 kb.formulas，不让 LLM 报数
"""

from __future__ import annotations

import json
import logging
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from chemaster.agent.context import ContextConfig, ContextManager
from chemaster.agent.types import (
    AssistantMessage,
    Dialog,
    MessageRole,
    StepRecord,
    SystemMessage,
    TaskInstance,
    ToolCall,
    ToolMessage,
    ToolSpec,
    ToolFunctionSchema,
    Trajectory,
    UserMessage,
)

logger = logging.getLogger(__name__)


class AgentConfig:
    """Agent 运行配置（轻量 dataclass）。"""

    def __init__(
        self,
        max_turns: int = 50,
        context_config: ContextConfig | None = None,
        finish_on_text_response: bool = False,
        show_in_console: bool = True,
        log_to_file: bool = False,
        runs_dir: str = "./runs",
    ) -> None:
        self.max_turns = max_turns
        self.context_config = context_config or ContextConfig()
        self.finish_on_text_response = finish_on_text_response
        self.show_in_console = show_in_console
        self.log_to_file = log_to_file
        self.runs_dir = Path(runs_dir)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AgentConfig":
        ctx_cfg = ContextConfig(**d.pop("context", {})) if "context" in d else None
        return cls(context_config=ctx_cfg, **d)


class BaseChemAgent(ABC):
    """ChemMaster Agent 执行核心抽象基类。

    子类需实现：
    - _get_system_prompt() → str
    - _get_user_prompt(task) → str
    - _get_tool_specs() → list[ToolSpec]
    - _execute_tool(tool_call) → (observation: str, info: dict)
    """

    VERSION = "0.1.0"

    # 类级别轨迹文件锁（多实例并发时共享文件安全）
    _trajectory_file_lock = threading.Lock()

    def __init__(
        self,
        config: AgentConfig | None = None,
        skill_registry=None,  # SkillRegistry | None
    ) -> None:
        self.config = config or AgentConfig()
        self.skill_registry = skill_registry
        self.context_manager = ContextManager(self.config.context_config)

        self.current_dialog: Dialog | None = None
        self.trajectory: Trajectory | None = None
        self._step_count = 0
        self._pending_ask_user: dict[str, Any] | None = None
        self._initial_system_prompt: str | None = None
        self._initial_user_prompt: str | None = None
        self._trajectory_file_path: Path | None = None

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    def run(self, task: TaskInstance, on_step=None) -> Trajectory:
        """执行一个任务（完整循环）。

        Args:
            task: 任务描述。
            on_step: 每步完成后的回调 (StepRecord, step_num, max_steps) → None。

        Returns:
            完整执行轨迹。
        """
        logger.info("Agent 开始执行任务: %s", task.task_id)
        self._initialize(task)

        try:
            for turn in range(self.config.max_turns):
                self._log_step_header(turn + 1, self.config.max_turns)
                should_finish = self._step()

                if on_step and self.trajectory and self.trajectory.steps:
                    try:
                        on_step(self.trajectory.steps[-1], turn + 1, self.config.max_turns)
                    except Exception as exc:
                        logger.warning("on_step 回调失败: %s", exc)

                if should_finish:
                    self._log_finish()
                    break
            else:
                logger.warning("⚠️  已达最大轮次上限 (%d)", self.config.max_turns)
                assert self.trajectory is not None
                self.trajectory.finish("failed", {"reason": "max_turns_exceeded"})

        except Exception as exc:
            logger.error("❌ Agent 执行异常: %s", exc)
            if self.trajectory:
                self.trajectory.finish("failed", {"reason": str(exc)})
            raise

        assert self.trajectory is not None
        return self.trajectory

    def continue_run(self, user_message: str, on_step=None) -> Trajectory:
        """追加用户消息，继续执行循环（多轮对话）。

        不会重新初始化，保留现有 context。
        适用于：TUI 中用户回复 ask_user 问题后继续。
        """
        if self.current_dialog is None:
            raise ValueError("Agent 尚未初始化，请先调用 run()。")

        logger.info("继续对话，新用户消息: %s…", user_message[:50])
        self.add_user_message(user_message)

        self.trajectory = Trajectory(
            task_id=f"continue_{self._step_count}",
            meta={"agent_version": self.VERSION, "task_type": "chat_continue"},
        )
        if self.current_dialog:
            self.trajectory.dialogs.append(self.current_dialog)
        self._step_count = 0

        try:
            for turn in range(self.config.max_turns):
                self._log_step_header(turn + 1, self.config.max_turns)
                should_finish = self._step()

                if on_step and self.trajectory.steps:
                    try:
                        on_step(self.trajectory.steps[-1], turn + 1, self.config.max_turns)
                    except Exception as exc:
                        logger.warning("on_step 回调失败: %s", exc)

                if should_finish:
                    self._log_finish()
                    break
            else:
                self.trajectory.finish("failed", {"reason": "max_turns_exceeded"})

        except Exception as exc:
            logger.error("❌ continue_run 异常: %s", exc)
            self.trajectory.finish("failed", {"reason": str(exc)})
            raise

        return self.trajectory

    # ------------------------------------------------------------------
    # 内部循环
    # ------------------------------------------------------------------

    def _initialize(self, task: TaskInstance) -> None:
        """初始化对话和轨迹。"""
        self.trajectory = Trajectory(
            task_id=task.task_id,
            meta={"agent_version": self.VERSION, "task_type": task.task_type},
        )

        system_prompt = self._get_system_prompt()
        user_prompt = self._get_user_prompt(task)

        self._initial_system_prompt = system_prompt
        self._initial_user_prompt = user_prompt

        self.current_dialog = Dialog(
            messages=[
                SystemMessage(content=system_prompt),
                UserMessage(content=user_prompt),
            ],
            tools=self._get_tool_specs(),
        )
        self.trajectory.dialogs.append(self.current_dialog)
        self._step_count = 0

    def _step(self) -> bool:
        """执行一步：query LLM → 处理 tool_calls → 记录轨迹。

        Returns:
            True 表示应结束循环（finish / ask_user / 无 tool call）。
        """
        assert self.current_dialog is not None
        self._step_count += 1

        # ① 准备 dialog（可能截断）
        dialog_for_query, compacted = self.context_manager.prepare_for_query(
            self.current_dialog
        )
        if compacted:
            self.current_dialog = dialog_for_query
            self.context_manager.reset_prompt_tokens()
            if self.trajectory and self.trajectory.dialogs:
                self.trajectory.dialogs[-1] = self.current_dialog

        # ② 调用 LLM
        try:
            assistant_message = self._query_llm(dialog_for_query)
        except Exception as exc:
            err_str = str(exc).lower()
            if "context" in err_str or "overflow" in err_str:
                logger.warning("Context 溢出，强制截断后重试")
                self.current_dialog = self.context_manager.truncate(self.current_dialog)
                self.context_manager.reset_prompt_tokens()
                if self.trajectory and self.trajectory.dialogs:
                    self.trajectory.dialogs[-1] = self.current_dialog
                assistant_message = self._query_llm(self.current_dialog)
            else:
                raise

        # 更新 token 用量
        usage = assistant_message.meta.get("usage", {})
        if usage:
            self.context_manager.update_usage(usage)
            if self.context_manager.is_overflow(usage):
                logger.info("Token 用量接近上限，主动截断")
                self.current_dialog = self.context_manager.truncate(self.current_dialog)
                self.context_manager.reset_prompt_tokens()

        self.current_dialog.add_message(assistant_message)

        step_record = StepRecord(
            step_id=self._step_count,
            assistant_message=assistant_message,
        )

        # ③ 处理 tool_calls
        if not assistant_message.tool_calls:
            # 无 tool call：根据配置决定是否结束
            if self.config.finish_on_text_response:
                assert self.trajectory is not None
                self.trajectory.add_step(step_record)
                self._append_trajectory_entry(step_record)
                self.trajectory.finish("completed")
                return True

            # 提示继续
            self._handle_no_tool_call()
            assert self.trajectory is not None
            self.trajectory.add_step(step_record)
            self._append_trajectory_entry(step_record)
            return False

        should_finish = False
        for tool_call in assistant_message.tool_calls:
            tool_name = tool_call.function.name

            # finish 工具
            if tool_name == "finish":
                self._log_finish_tool(tool_call)
                tool_msg = ToolMessage(
                    content="任务已标记为完成。",
                    tool_call_id=tool_call.id,
                    name="finish",
                    meta={"task_completed": True},
                )
                self.current_dialog.add_message(tool_msg)
                step_record.tool_responses.append(tool_msg)
                should_finish = True
                break

            # ask_user 工具（暂停等待用户输入）
            if tool_name == "ask_user":
                self._handle_ask_user(tool_call, step_record)
                should_finish = True
                break

            # 普通工具调用
            observation, info = self._execute_tool_safe(tool_call)
            tool_msg = ToolMessage(
                content=observation,
                tool_call_id=tool_call.id,
                name=tool_name,
                meta={"info": info},
            )
            self.current_dialog.add_message(tool_msg)
            step_record.tool_responses.append(tool_msg)

        assert self.trajectory is not None
        self.trajectory.add_step(step_record)
        self._append_trajectory_entry(step_record)

        if should_finish:
            if self._pending_ask_user:
                self.trajectory.finish("waiting_for_input", self._pending_ask_user)
                self._pending_ask_user = None
            else:
                self.trajectory.finish("completed")

        return should_finish

    def _handle_no_tool_call(self) -> None:
        """无 tool call 时提示 LLM 继续工作。"""
        prompt = (
            "请继续完成任务。\n"
            "如果需要计算化学帮助，使用 use_skill 工具获取方法论指导。\n"
            "任务完成后，使用 finish 工具标记完成。\n"
            "如需用户决策，使用 ask_user 工具。"
        )
        self.current_dialog.add_message(UserMessage(content=prompt))

    def _handle_ask_user(self, tool_call: ToolCall, step_record: StepRecord) -> None:
        """处理 ask_user 工具调用，暂停等待用户输入。"""
        try:
            args = json.loads(tool_call.function.arguments or "{}")
            self._pending_ask_user = {
                "ask_user": True,
                "questions": args.get("questions", []),
                "context": args.get("context", ""),
            }
        except json.JSONDecodeError:
            self._pending_ask_user = {"ask_user": True, "questions": []}

        logger.info("❓ ask_user: Agent 暂停，等待用户输入")
        if self.config.show_in_console:
            questions = self._pending_ask_user.get("questions", [])
            for q in questions:
                print(f"\n  ❓ {q}")

        tool_msg = ToolMessage(
            content="问题已发送给用户，等待回复。",
            tool_call_id=tool_call.id,
            name="ask_user",
            meta={"pending": self._pending_ask_user},
        )
        self.current_dialog.add_message(tool_msg)
        step_record.tool_responses.append(tool_msg)

    def _execute_tool_safe(self, tool_call: ToolCall) -> tuple[str, dict[str, Any]]:
        """安全执行工具，捕获所有异常。"""
        tool_name = tool_call.function.name
        tool_args = tool_call.function.arguments

        self._log_tool_start(tool_name, tool_args)

        try:
            observation, info = self._execute_tool(tool_call)
        except Exception as exc:
            observation = f"工具执行异常 [{tool_name}]: {type(exc).__name__}: {exc}"
            info = {"error": str(exc)}
            logger.error("工具 '%s' 执行失败: %s", tool_name, exc, exc_info=True)

        # 截断超长输出
        max_chars = self.config.context_config.max_tool_output_chars
        if len(observation) > max_chars:
            half = max_chars // 2
            observation = (
                observation[:half]
                + f"\n\n... [输出过长，截断] ...\n\n"
                + observation[-half:]
            )

        self._log_tool_end(tool_name, observation)
        return observation, info

    # ------------------------------------------------------------------
    # 轨迹记录
    # ------------------------------------------------------------------

    def set_trajectory_file(self, path: str | Path) -> None:
        """设置轨迹 JSON 文件路径（每步追加写入）。"""
        self._trajectory_file_path = Path(path)
        self._trajectory_file_path.parent.mkdir(parents=True, exist_ok=True)

    def _append_trajectory_entry(self, step_record: StepRecord) -> None:
        """将当前步骤追加写入轨迹文件（thread-safe）。"""
        if self._trajectory_file_path is None:
            return

        try:
            entry = {
                "task_id": self.trajectory.task_id if self.trajectory else "unknown",
                "step": self._step_count,
                "assistant": {
                    "content": step_record.assistant_message.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        }
                        for tc in step_record.assistant_message.tool_calls
                    ],
                },
                "tool_responses": [
                    {
                        "name": tr.name,
                        "content": tr.content[:500],  # 截断避免文件过大
                    }
                    for tr in step_record.tool_responses
                ],
                "timestamp": step_record.timestamp,
            }

            with self._trajectory_file_lock:
                existing: list = []
                if self._trajectory_file_path.exists():
                    try:
                        existing = json.loads(
                            self._trajectory_file_path.read_text(encoding="utf-8")
                        )
                    except (json.JSONDecodeError, OSError):
                        existing = []
                existing.append(entry)
                self._trajectory_file_path.write_text(
                    json.dumps(existing, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
        except Exception as exc:
            logger.warning("轨迹写入失败（不影响执行）: %s", exc)

    # ------------------------------------------------------------------
    # 对话管理
    # ------------------------------------------------------------------

    def add_user_message(self, content: str) -> None:
        if self.current_dialog is None:
            raise ValueError("Agent 未初始化")
        self.current_dialog.add_message(UserMessage(content=content))

    def reset_context(self) -> None:
        """重置 context 到初始状态（仅保留 system + 第一条 user）。"""
        if self._initial_system_prompt is None:
            raise ValueError("Agent 未初始化，无法重置")
        self.current_dialog = Dialog(
            messages=[
                SystemMessage(content=self._initial_system_prompt),
                *(
                    [UserMessage(content=self._initial_user_prompt)]
                    if self._initial_user_prompt
                    else []
                ),
            ],
            tools=self._get_tool_specs(),
        )
        self._step_count = 0
        logger.info("Context 已重置到初始状态")

    # ------------------------------------------------------------------
    # 日志辅助
    # ------------------------------------------------------------------

    def _log_step_header(self, step: int, max_steps: int) -> None:
        if self.config.show_in_console:
            print(f"\n{'='*60}")
            print(f"📍 Step [{step}/{max_steps}]")
            print(f"{'='*60}")
        logger.info("=" * 60)
        logger.info("📍 Step [%d/%d]", step, max_steps)
        logger.info("=" * 60)

    def _log_finish(self) -> None:
        assert self.trajectory is not None
        if self._pending_ask_user:
            logger.info("⏸️  Agent 暂停，等待用户输入")
        else:
            logger.info("✅ Agent 完成任务: %s", self.trajectory.task_id)
        if self.config.show_in_console:
            print(f"\n{'='*60}")
            status = "⏸️  等待用户输入" if self._pending_ask_user else "✅ 任务完成"
            print(status)
            print(f"{'='*60}")

    def _log_tool_start(self, tool_name: str, tool_args: str) -> None:
        if self.config.show_in_console:
            print(f"\n[🔧 Tool] {tool_name}")
            try:
                parsed = json.loads(tool_args)
                print(f"  参数: {json.dumps(parsed, indent=2, ensure_ascii=False)}")
            except Exception:
                print(f"  参数: {tool_args}")

    def _log_tool_end(self, tool_name: str, observation: str) -> None:
        if self.config.show_in_console:
            preview = observation[:200].replace("\n", " ")
            print(f"  结果: {preview}{'…' if len(observation) > 200 else ''}")

    def _log_finish_tool(self, tool_call: ToolCall) -> None:
        try:
            args = json.loads(tool_call.function.arguments or "{}")
            if self.config.show_in_console:
                print("\n📝 finish 工具参数:")
                for k, v in args.items():
                    print(f"  {k}: {str(v)[:200]}")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 子类实现
    # ------------------------------------------------------------------

    @abstractmethod
    def _query_llm(self, dialog: Dialog) -> AssistantMessage:
        """调用 LLM，返回 AssistantMessage。子类负责持有 LLM 实例。"""

    @abstractmethod
    def _get_system_prompt(self) -> str:
        """构建 system prompt（含 Skill 摘要）。"""

    @abstractmethod
    def _get_user_prompt(self, task: TaskInstance) -> str:
        """构建用户初始 prompt。"""

    @abstractmethod
    def _get_tool_specs(self) -> list[ToolSpec]:
        """返回暴露给 LLM 的工具规格列表。"""

    @abstractmethod
    def _execute_tool(self, tool_call: ToolCall) -> tuple[str, dict[str, Any]]:
        """执行工具调用，返回 (observation, info)。"""
