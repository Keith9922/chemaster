"""Agent core type system.

Defines the data classes used by the Agent loop:

- Message types (System / User / Assistant / Tool)
- Dialog (message list + tool specs sent to LLM)
- ToolCall / ToolSpec (tool-use protocol shape)
- StepRecord / Trajectory (persisted trace for replay & debugging)
- TaskInstance (single task definition)

Design references:
- EvoMaster's evomaster/utils/types.py (overall shape, role-based messages)
- Anthropic SDK's tool_use / tool_result blocks (interop format)

These types are LLM-vendor agnostic. AnthropicLLM (in llm_client.py) is
responsible for translating to/from Anthropic's wire format.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


# ══════════════════════════════════════════════════════════════════════════════
# Tool-use protocol
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class ToolCall:
    """A single tool invocation requested by the LLM."""

    id: str                              # provider-assigned id (e.g. toolu_xxx)
    name: str                            # tool name
    arguments: dict[str, Any]            # parsed JSON args

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "arguments": self.arguments}


@dataclass
class ToolSpec:
    """Tool description sent to the LLM (input_schema in Anthropic terms)."""

    name: str
    description: str
    input_schema: dict[str, Any]         # JSON Schema dict

    def to_anthropic(self) -> dict:
        """Anthropic API tool block."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


# ══════════════════════════════════════════════════════════════════════════════
# Messages
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class SystemMessage:
    content: str
    role: Role = Role.SYSTEM

    def to_dict(self) -> dict:
        return {"role": self.role.value, "content": self.content}


@dataclass
class UserMessage:
    content: str
    role: Role = Role.USER

    def to_dict(self) -> dict:
        return {"role": self.role.value, "content": self.content}


@dataclass
class AssistantMessage:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    role: Role = Role.ASSISTANT
    meta: dict[str, Any] = field(default_factory=dict)   # usage, stop_reason, etc.

    def to_dict(self) -> dict:
        return {
            "role": self.role.value,
            "content": self.content,
            "tool_calls": [tc.to_dict() for tc in self.tool_calls],
            "meta": self.meta,
        }


@dataclass
class ToolMessage:
    """Tool execution result fed back to the LLM."""

    content: str                          # human-readable observation
    tool_call_id: str                     # links back to ToolCall.id
    name: str                             # tool name (redundant, helps debugging)
    role: Role = Role.TOOL
    is_error: bool = False
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "role": self.role.value,
            "tool_call_id": self.tool_call_id,
            "name": self.name,
            "content": self.content,
            "is_error": self.is_error,
            "meta": self.meta,
        }


Message = SystemMessage | UserMessage | AssistantMessage | ToolMessage


# ══════════════════════════════════════════════════════════════════════════════
# Dialog
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class Dialog:
    """An ordered list of messages plus the tool specs available this turn."""

    messages: list[Message] = field(default_factory=list)
    tools: list[ToolSpec] = field(default_factory=list)

    def add_message(self, msg: Message) -> None:
        self.messages.append(msg)

    def to_dict(self) -> dict:
        return {
            "messages": [m.to_dict() for m in self.messages],
            "tools": [
                {"name": t.name, "description": t.description, "input_schema": t.input_schema}
                for t in self.tools
            ],
        }


# ══════════════════════════════════════════════════════════════════════════════
# Trajectory (persistence layer)
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class StepRecord:
    """One iteration of the Agent loop."""

    step_id: int
    assistant_message: AssistantMessage | None = None
    tool_responses: list[ToolMessage] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "step_id": self.step_id,
            "timestamp": self.timestamp,
            "assistant_message": self.assistant_message.to_dict() if self.assistant_message else None,
            "tool_responses": [tr.to_dict() for tr in self.tool_responses],
            "meta": self.meta,
        }


@dataclass
class Trajectory:
    """End-to-end record of one task: prompt → agent loop → result."""

    task_id: str = field(default_factory=lambda: f"task-{uuid.uuid4().hex[:8]}")
    status: str = "running"               # running | completed | failed | waiting_for_input
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    finished_at: str | None = None
    steps: list[StepRecord] = field(default_factory=list)
    finish_payload: dict[str, Any] | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def add_step(self, step: StepRecord) -> None:
        self.steps.append(step)

    def finish(self, status: str, payload: dict | None = None) -> None:
        self.status = status
        self.finished_at = datetime.now(timezone.utc).isoformat()
        if payload is not None:
            self.finish_payload = payload

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "steps": [s.to_dict() for s in self.steps],
            "finish_payload": self.finish_payload,
            "meta": self.meta,
        }

    def save(self, path: str | Path) -> None:
        Path(path).write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


# ══════════════════════════════════════════════════════════════════════════════
# Task input
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class TaskInstance:
    """A single user-issued chemistry task."""

    description: str
    task_id: str = field(default_factory=lambda: f"task-{uuid.uuid4().hex[:8]}")
    task_type: str = "chemistry"          # chemistry | benchmark | replay | …
    input_data: str = ""                  # additional context (xyz, SMILES, etc.)
    images: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)
