"""Agent 消息类型系统 —— 参考 EvoMaster utils/types.py，结合计算化学场景扩展。

核心模型：
- Message 层级：SystemMessage / UserMessage / AssistantMessage / ToolMessage
- ToolCall / ToolCallFunction：LLM 返回的工具调用
- Dialog：一次对话的完整消息序列 + 工具规格
- StepRecord：单步执行记录（LLM 响应 + 工具返回）
- Trajectory：完整执行轨迹（含所有 step + 最终状态）
- TaskInstance：传给 Agent.run() 的任务描述
"""

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 消息角色
# ---------------------------------------------------------------------------

class MessageRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


# ---------------------------------------------------------------------------
# 消息类型
# ---------------------------------------------------------------------------

class BaseMessage(BaseModel):
    """所有消息的基类。"""
    role: MessageRole
    content: str = ""
    meta: dict[str, Any] = Field(default_factory=dict)


class SystemMessage(BaseMessage):
    role: MessageRole = MessageRole.SYSTEM


class UserMessage(BaseMessage):
    role: MessageRole = MessageRole.USER


class ToolCallFunction(BaseModel):
    """LLM 返回的工具调用函数信息。"""
    name: str
    arguments: str  # JSON 字符串


class ToolCall(BaseModel):
    """LLM 返回的单次工具调用。"""
    id: str = Field(default_factory=lambda: f"call_{uuid.uuid4().hex[:8]}")
    type: str = "function"
    function: ToolCallFunction


class AssistantMessage(BaseMessage):
    """LLM 的响应消息，可能含工具调用。"""
    role: MessageRole = MessageRole.ASSISTANT
    tool_calls: list[ToolCall] = Field(default_factory=list)


class ToolMessage(BaseMessage):
    """工具调用结果消息。"""
    role: MessageRole = MessageRole.TOOL
    tool_call_id: str = ""
    name: str = ""  # 对应的工具名


# ---------------------------------------------------------------------------
# 工具规格（传给 LLM 的 schema）
# ---------------------------------------------------------------------------

class ToolFunctionSchema(BaseModel):
    name: str
    description: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)


class ToolSpec(BaseModel):
    type: str = "function"
    function: ToolFunctionSchema


# ---------------------------------------------------------------------------
# Dialog —— 一次完整对话
# ---------------------------------------------------------------------------

class Dialog(BaseModel):
    """一次对话的完整消息序列。"""
    messages: list[BaseMessage] = Field(default_factory=list)
    tools: list[ToolSpec] = Field(default_factory=list)

    def add_message(self, msg: BaseMessage) -> None:
        self.messages.append(msg)

    def clone(self) -> "Dialog":
        """浅复制，messages 列表独立但 msg 对象共享。"""
        return Dialog(
            messages=list(self.messages),
            tools=list(self.tools),
        )


# ---------------------------------------------------------------------------
# StepRecord —— 单步执行记录
# ---------------------------------------------------------------------------

class StepRecord(BaseModel):
    """单步执行记录：LLM 的响应 + 所有工具返回。"""
    step_id: int
    assistant_message: AssistantMessage
    tool_responses: list[ToolMessage] = Field(default_factory=list)
    timestamp: float = Field(default_factory=time.time)
    meta: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Trajectory —— 完整执行轨迹
# ---------------------------------------------------------------------------

class Trajectory(BaseModel):
    """一次任务的完整执行轨迹。

    计算化学扩展：含 plan_json 和 calc_results，便于 3 个月后复现。
    """
    task_id: str
    dialogs: list[Dialog] = Field(default_factory=list)
    steps: list[StepRecord] = Field(default_factory=list)
    status: str = "running"           # running / completed / failed / waiting_for_input
    result: dict[str, Any] = Field(default_factory=dict)
    meta: dict[str, Any] = Field(default_factory=dict)
    start_time: float = Field(default_factory=time.time)
    end_time: float | None = None

    # 计算化学专属字段
    plan_json: dict[str, Any] | None = None   # 序列化的 Plan 对象
    calc_results: list[dict[str, Any]] = Field(default_factory=list)  # MCP 返回的计算结果

    def add_step(self, step: StepRecord) -> None:
        self.steps.append(step)

    def finish(
        self,
        status: str,
        result: dict[str, Any] | None = None,
    ) -> None:
        self.status = status
        self.result = result or {}
        self.end_time = time.time()


# ---------------------------------------------------------------------------
# TaskInstance —— 传给 Agent.run() 的任务描述
# ---------------------------------------------------------------------------

class TaskInstance(BaseModel):
    """一个待执行的任务。"""
    task_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    task_type: str = "general"        # general / opt_freq / tddft / tadf_pipeline …
    description: str = ""
    input_data: dict[str, Any] = Field(default_factory=dict)
    # 计算化学专属
    smiles: str | None = None
    molecule_name: str | None = None
    charge: int = 0
    multiplicity: int = 1
