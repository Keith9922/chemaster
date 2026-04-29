"""Tool registry — Agent-facing abstraction over MCP servers and built-ins.

Design borrowed from Claude Code's `Tool.ts` (per-tool permissions, read-only
flag, concurrency safety) and EvoMaster's `ToolRegistry` (registration +
spec generation).

Key concepts:
- Each tool exposes JSON Schema (`input_schema`) the LLM uses for arg planning.
- Each tool *self-declares* permission flags:
    `is_read_only`        — does this only read state? (parallel-safe, no confirm)
    `is_destructive`      — writes, irreversible, or visible to others (confirm)
    `is_long_running`     — wall-clock typically > 30 s (confirm)
- Confirmation flow is per-tool, NOT a central token gate. The Agent loop
  consults the tool's flags + a `confirm_callback` from the UI.

Existing MCP servers are wrapped via `MCPToolAdapter` so we don't have to
rewrite them.
"""

from __future__ import annotations

import inspect
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable

from chemaster.agent.types import ToolSpec

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# Tool result
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class ToolResult:
    """Normalized return shape from any tool."""

    ok: bool
    observation: str                       # human-readable string for the LLM
    data: dict[str, Any] | None = None     # structured payload (optional)
    is_error: bool = False                 # set True for unrecoverable / type errors

    def to_observation(self) -> str:
        return self.observation


# ══════════════════════════════════════════════════════════════════════════════
# BaseTool
# ══════════════════════════════════════════════════════════════════════════════


class BaseTool(ABC):
    """Abstract tool. Subclasses implement `run()` and provide schema."""

    name: str = ""
    description: str = ""
    input_schema: dict[str, Any] = {"type": "object", "properties": {}}

    # Permission flags
    is_read_only: bool = False             # safe to run in parallel, no confirm
    is_destructive: bool = False           # irreversible / external side-effect
    is_long_running: bool = False          # wall clock > 30 s expected

    @abstractmethod
    def run(self, **kwargs) -> ToolResult:
        """Execute the tool. Always return ToolResult; never raise to the Agent."""

    def to_spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.name,
            description=self.description,
            input_schema=self.input_schema,
        )

    def needs_confirmation(self) -> bool:
        return self.is_destructive or self.is_long_running


# ══════════════════════════════════════════════════════════════════════════════
# MCPToolAdapter — wrap an existing FastMCP function as a BaseTool
# ══════════════════════════════════════════════════════════════════════════════


class MCPToolAdapter(BaseTool):
    """Adapt a FastMCP-decorated tool function (returning dict) to BaseTool.

    The MCP tool is expected to return a dict. We:
    1. Coerce ok-flag from {ok}, defaulting to True.
    2. Build a human-readable observation that includes the structured payload.
    3. Surface error_code / suggestion when present.
    """

    def __init__(
        self,
        fn: Callable,
        name: str,
        description: str,
        input_schema: dict | None = None,
        is_read_only: bool = False,
        is_destructive: bool = False,
        is_long_running: bool = False,
    ) -> None:
        self._fn = fn
        self.name = name
        self.description = description or (inspect.getdoc(fn) or "").strip() or name
        self.input_schema = input_schema or self._infer_schema(fn)
        self.is_read_only = is_read_only
        self.is_destructive = is_destructive
        self.is_long_running = is_long_running

    def run(self, **kwargs) -> ToolResult:
        try:
            result = self._fn(**kwargs)
        except TypeError as exc:
            return ToolResult(
                ok=False,
                observation=f"Tool {self.name} called with invalid arguments: {exc}",
                data={"error_code": "INVALID_ARGS", "details": str(exc)},
                is_error=True,
            )
        except Exception as exc:
            logger.exception("MCP tool %s raised", self.name)
            return ToolResult(
                ok=False,
                observation=f"Tool {self.name} raised: {type(exc).__name__}: {exc}",
                data={"error_code": "TOOL_EXCEPTION", "details": str(exc)},
                is_error=True,
            )

        if not isinstance(result, dict):
            return ToolResult(
                ok=False,
                observation=f"Tool {self.name} returned non-dict: {type(result).__name__}",
                data={"error_code": "BAD_RETURN_SHAPE"},
                is_error=True,
            )

        return self._format_result(result)

    def _format_result(self, result: dict) -> ToolResult:
        ok = result.get("ok", True)
        if not ok:
            error_code = result.get("error_code", "UNKNOWN_ERROR")
            details = result.get("details", "")
            suggestion = result.get("suggestion", "")
            obs_lines = [f"[{error_code}]"]
            if details:
                obs_lines.append(f"Details: {details}")
            if suggestion:
                obs_lines.append(f"Suggestion: {suggestion}")
            return ToolResult(
                ok=False,
                observation="\n".join(obs_lines),
                data=result,
            )

        # Success path — build a compact summary.
        payload = result.get("result", {key: v for key, v in result.items() if key != "ok"})
        warnings = result.get("warnings") or []
        obs_lines = [f"[OK] {self.name}"]
        if isinstance(payload, dict) and payload:
            obs_lines.append(self._summarize(payload))
        if warnings:
            obs_lines.append("Warnings: " + "; ".join(self._fmt_warning(w) for w in warnings))
        return ToolResult(
            ok=True,
            observation="\n".join(obs_lines),
            data=result,
        )

    @staticmethod
    def _summarize(payload: dict, max_chars: int = 1200) -> str:
        import json
        try:
            text = json.dumps(payload, ensure_ascii=False, default=str, indent=2)
        except (TypeError, ValueError):
            text = str(payload)
        if len(text) > max_chars:
            text = text[: max_chars // 2] + "\n... [truncated] ...\n" + text[-max_chars // 2 :]
        return text

    @staticmethod
    def _fmt_warning(w) -> str:
        if isinstance(w, str):
            return w
        if isinstance(w, dict):
            code = w.get("code", "")
            message = w.get("message", str(w))
            return f"{code}: {message}".lstrip(": ")
        return str(w)

    @staticmethod
    def _infer_schema(fn: Callable) -> dict:
        """Build a JSON Schema from the function signature (best-effort)."""
        sig = inspect.signature(fn)
        properties: dict[str, dict] = {}
        required: list[str] = []
        for pname, param in sig.parameters.items():
            if pname.startswith("_"):
                continue
            ann = param.annotation
            jtype = "string"
            if ann is int:
                jtype = "integer"
            elif ann is float:
                jtype = "number"
            elif ann is bool:
                jtype = "boolean"
            elif ann is dict or str(ann).startswith("dict"):
                jtype = "object"
            elif ann is list or str(ann).startswith("list"):
                jtype = "array"
            properties[pname] = {"type": jtype}
            if param.default is inspect.Parameter.empty:
                required.append(pname)
        schema: dict[str, Any] = {"type": "object", "properties": properties}
        if required:
            schema["required"] = required
        return schema


# ══════════════════════════════════════════════════════════════════════════════
# ToolRegistry
# ══════════════════════════════════════════════════════════════════════════════


class ToolRegistry:
    """Holds all registered tools; the Agent looks them up by name."""

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        if not tool.name:
            raise ValueError(f"Cannot register tool without a name: {tool!r}")
        if tool.name in self._tools:
            logger.warning("Replacing existing tool registration: %s", tool.name)
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def has(self, name: str) -> bool:
        return name in self._tools

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def specs(self, enabled: list[str] | None = None) -> list[ToolSpec]:
        if enabled is None:
            tools = list(self._tools.values())
        else:
            allowed = set(enabled)
            tools = [t for t in self._tools.values() if t.name in allowed]
        return [t.to_spec() for t in tools]

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)
