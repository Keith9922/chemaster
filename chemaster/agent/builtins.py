"""Built-in tools the Agent always has access to.

- `FinishTool`     — Agent signals task completion (returns the final summary).
- `AskUserTool`    — Agent pauses execution and waits for user input.
- `ThinkTool`      — Free-form reasoning step that doesn't touch the world.
- `RecommendTool`  — Agent surfaces a chemistry decision with reasoning and
                     waits for user accept / modify / cancel. v3.0 addition.

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
        "is fully answered. If a recommendation was overridden by the user, "
        "mention it in the summary so the trajectory tells a coherent story."
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
        "Pause execution and ask the user a clarifying question. Use when the "
        "task description is genuinely ambiguous (e.g. 'optimize the molecule' "
        "with multiple molecules in scope), when no reasonable default exists "
        "to recommend (e.g. multiplicity for a borderline-radical species), "
        "or when prior recommendations have been rejected and you need fresh "
        "guidance. For routine method/basis choices where you have a good "
        "default, use `recommend` instead — it's a softer interrupt."
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


class RecommendTool(BaseTool):
    """Surface a chemistry decision to the user with your recommendation.

    Use this BEFORE applying any choice that affects the chemistry of the
    result (functional, basis, solvation model, multiplicity, treating a
    structure as a TS vs a minimum, switching method after failure).

    The user may:
    - **accept**: proceed with the recommended value
    - **modify**: change the value before proceeding
    - **cancel**: abort the task

    The agent loop intercepts this tool call and renders it as a recommend
    card in the active frontend (CLI / TUI / Web). The response carries the
    user's decision back into the dialog as a tool_result.
    """

    name = "recommend"
    description = (
        "Surface a chemistry decision to the user with your recommendation "
        "and reasoning. Use this BEFORE calling computational tools with "
        "non-default chemistry parameters. The user may accept your "
        "recommendation, modify it, or cancel the task. Do not silently apply "
        "non-default chemistry choices — every method/basis/functional/solvent "
        "choice that affects the scientific answer must pass through here, "
        "unless the user has demoted that decision to L1 in their policy file."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "decision": {
                "type": "string",
                "description": (
                    "Short label of the decision being made, e.g. "
                    "'functional for S1 optimization' or 'basis set for "
                    "transition-metal opt' or 'how to handle 1 imaginary mode'."
                ),
            },
            "recommendation": {
                "type": "string",
                "description": (
                    "Your recommended choice as a concise string the user can "
                    "evaluate at a glance, e.g. 'CAM-B3LYP / def2-TZVP, TDA' "
                    "or 'displace along mode -23 cm-1, re-optimize, retry "
                    "frequency'."
                ),
            },
            "reasoning": {
                "type": "string",
                "description": (
                    "Why this recommendation, given the system size, target "
                    "property, and any KB / skill context. One paragraph."
                ),
            },
            "alternatives": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Other reasonable choices the user might prefer, with a "
                    "brief tradeoff each. Optional but encouraged for any "
                    "decision the user might reasonably override."
                ),
            },
            "tradeoffs": {
                "type": "string",
                "description": (
                    "Cost / accuracy / wall-time tradeoffs. Optional."
                ),
            },
            "decision_class": {
                "type": "string",
                "enum": ["method", "basis", "functional", "solvation",
                         "multiplicity", "ts_or_min", "method_substitution",
                         "backend_switch", "other"],
                "description": (
                    "Category of the decision; used by the policy layer to "
                    "decide whether this recommendation is L2 or L3."
                ),
            },
        },
        "required": ["decision", "recommendation", "reasoning"],
    }

    # Recommendations always require user input — the agent must wait for the
    # decision before proceeding. Marked is_read_only since the tool itself
    # has no side effect; the user's decision drives any subsequent action.
    is_read_only = True
    # is_chemistry_decision is a v3.0 flag used by the policy layer.
    is_chemistry_decision = True

    def run(
        self,
        decision: str = "",
        recommendation: str = "",
        reasoning: str = "",
        alternatives: list[str] | None = None,
        tradeoffs: str = "",
        decision_class: str = "other",
    ) -> ToolResult:
        # The actual interaction is intercepted by the Agent loop. This run()
        # is a defensive fallback that produces a benign observation.
        return ToolResult(
            ok=True,
            observation=(
                f"[recommend] {decision}: {recommendation} (reasoning: "
                f"{reasoning[:200]}...) — awaiting user decision"
            ),
            data={
                "decision": decision,
                "recommendation": recommendation,
                "reasoning": reasoning,
                "alternatives": alternatives or [],
                "tradeoffs": tradeoffs,
                "decision_class": decision_class,
            },
        )


def register_builtins(registry) -> None:
    """Attach builtins to a ToolRegistry instance."""
    registry.register(FinishTool())
    registry.register(AskUserTool())
    registry.register(ThinkTool())
    registry.register(RecommendTool())
