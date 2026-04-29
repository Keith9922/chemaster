"""Built-in tools the Agent always has access to.

- `FinishTool`  — Agent signals task completion (returns the final summary).
- `AskUserTool` — Agent pauses execution and waits for user input.
- `ThinkTool`   — Free-form reasoning step that doesn't touch the world; helps
                  Claude organize its plan before calling expensive tools.

These are intercepted by the Agent loop (see agent.py); they don't actually
"run" in the normal sense. Run() returns a benign observation so the dialog
stays valid even if the loop didn't intercept (defensive).
"""

from __future__ import annotations

from chemaster.agent.tool_registry import BaseTool, ToolResult


class FinishTool(BaseTool):
    name = "finish"
    description = (
        "Signal that the task is complete. Provide a short summary of what was "
        "accomplished and the headline numbers (e.g. final energy in Hartree, "
        "ZPE, dominant frequencies). Always call this once the user's question "
        "is fully answered."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "1–3 paragraph summary of what was done and the result.",
            },
            "key_results": {
                "type": "object",
                "description": (
                    "Structured headline numbers, e.g. "
                    "{'final_energy_Hartree': -76.42, 'zpe_eV': 0.57}."
                ),
            },
        },
        "required": ["summary"],
    }

    is_read_only = True

    def run(self, summary: str = "", key_results: dict | None = None) -> ToolResult:
        return ToolResult(
            ok=True,
            observation=f"[finished]\n{summary}",
            data={"summary": summary, "key_results": key_results or {}},
        )


class AskUserTool(BaseTool):
    name = "ask_user"
    description = (
        "Pause execution and ask the user a clarifying question. Use sparingly: "
        "only when the task description is genuinely ambiguous (e.g. 'optimize "
        "the molecule' with multiple molecules in scope) or when the user must "
        "decide between options that have meaningfully different consequences "
        "(cost, accuracy, scope)."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "questions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of questions to ask the user.",
            },
            "context": {
                "type": "string",
                "description": "Why you need this information.",
            },
        },
        "required": ["questions"],
    }

    is_read_only = True

    def run(self, questions: list[str] | None = None, context: str = "") -> ToolResult:
        qs = questions or []
        return ToolResult(
            ok=True,
            observation="[ask_user] Awaiting user response: " + " | ".join(qs),
            data={"questions": qs, "context": context},
        )


class ThinkTool(BaseTool):
    name = "think"
    description = (
        "Reason out loud about the next step without invoking any external tool. "
        "Useful for: (1) interpreting a tool result before deciding the next "
        "call, (2) sketching a plan for a multi-step calculation, (3) checking "
        "whether the user's intent is fully covered. This call has no side "
        "effects and is cheap, but it does not move the calculation forward — "
        "actually call computational tools when you need numbers."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "thought": {
                "type": "string",
                "description": "Free-form reasoning text.",
            },
        },
        "required": ["thought"],
    }

    is_read_only = True

    def run(self, thought: str = "") -> ToolResult:
        return ToolResult(
            ok=True,
            observation="[thought recorded]",
            data={"thought": thought},
        )


def register_builtins(registry) -> None:
    """Attach builtins to a ToolRegistry instance."""
    registry.register(FinishTool())
    registry.register(AskUserTool())
    registry.register(ThinkTool())
