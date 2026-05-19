"""Deterministic keyword-routing MockLLM responder.

Used by:
  - ``scripts/benchmarks/run_execution_and_scalability.py`` (response-rate
    + scalability benchmarks, §4.4.2 / §4.4.3 of the thesis)
  - ``chemaster.mcp.agent.server`` — for cross-client MCP demos without
    requiring a real LLM API key on the host machine.

The responder is bilingual (English + Chinese keywords) and returns a
single tool call on the first visit, then ``finish`` on the second.
Suitable for protocol-compliance demos but **not** a substitute for a
real LLM — methods/basis sets are chosen by keyword match, not chemistry.
"""

from __future__ import annotations

from typing import Any, Callable

# Same H2 geometry the benchmark script uses, kept tiny so test runs stay fast.
_DEFAULT_H2_XYZ = "2\nH2\nH 0.0 0.0 0.0\nH 0.0 0.0 0.74\n"


def build_routing_responder(
    *,
    h2_xyz: str = _DEFAULT_H2_XYZ,
    fallback_constant: str = "planck",
) -> Callable[[Any], Any]:
    """Build a responder closure suitable for ``MockLLM(responder=...)``.

    The responder maintains a small private state dict that tracks the step
    count so the second visit always returns ``finish``. Reset between agent
    runs by calling ``responder.reset()``.

    Args:
        h2_xyz: XYZ block to pass when an energy/optimize tool is selected.
        fallback_constant: name to pass when the intent doesn't match any
            keyword bucket and we fall back to ``const_get``.

    Returns:
        A callable ``responder(dialog) -> AssistantMessage`` with an extra
        ``responder.reset()`` method.
    """
    from chemaster.agent.types import AssistantMessage, ToolCall

    state = {"step": 0}

    def _route_first_visit(intent: str):
        """Pick a tool call from intent keywords (single-pass keyword router)."""
        # NB: skill must be checked BEFORE the generic kb-search keywords so
        # that "use skill" / "应用 skill" routes to use_skill, not kb_search.
        if any(k in intent for k in (
                "use_skill", "use skill", "apply skill",
                "load the", "调用 use_skill",
                "应用 use skill", "使用 skill",
                "应用 skill", "调用 skill",
                "加载 skill", "使用 use_skill")) or (
                "skill" in intent and any(k in intent for k in (
                    "use", "apply", "load", "使用", "应用", "调用", "加载"))):
            return ToolCall(id="c1", name="use_skill",
                            arguments={"name": "opt-freq", "action": "get_info"})

        if any(k in intent for k in (
                # English energy intents
                "energy", "energies", "compute", "single point", "scf",
                # Chinese energy intents
                "能量", "能 量", "单点", "单点能", "电子能", "总能量",
                "用 hf 算", "做 scf", "做一个 scf")):
            return ToolCall(id="c1", name="calc_psi4_single_point",
                            arguments={
                                "geometry_xyz": h2_xyz,
                                "method": "B3LYP-D3BJ",
                                "basis": "sto-3g",
                                "charge": 0,
                                "multiplicity": 1,
                            })

        if any(k in intent for k in (
                "optimize", "optimise", "geometry", "minimum", "equilibrium",
                "minimise", "minimize", "equilibrium structure",
                # Chinese — multiple common phrasings for geometry optimization
                "优化", "几何", "极小值", "最小值",
                "平衡结构", "平衡构型", "平衡几何",
                "结构优化", "构型优化")):
            return ToolCall(id="c1", name="calc_psi4_single_point",
                            arguments={
                                "geometry_xyz": h2_xyz,
                                "method": "HF",
                                "basis": "sto-3g",
                                "charge": 0,
                                "multiplicity": 1,
                            })

        if any(k in intent for k in (
                "constant", "convert", "unit", "hartree", "ev",
                # Chinese
                "常数", "换算", "转换", "数值", "光速", "玻尔兹曼",
                "阿伏伽德罗", "普朗克", "物理常数")):
            return ToolCall(id="c1", name="const_get",
                            arguments={"name": "planck"})

        if any(k in intent for k in (
                "skill", "playbook", "search", "kb", "knowledge",
                # Chinese
                "知识库", "搜索", "搜 ", "查 ", "找 ", "检索", "playbook")):
            return ToolCall(id="c1", name="kb_search",
                            arguments={"query": intent[:30] or "tddft"})

        # Fallback: a safe read-only constant lookup.
        return ToolCall(id="c1", name="const_get",
                        arguments={"name": fallback_constant})

    def responder(dialog):
        # Find the last user message — that's the active intent.
        last_user = None
        for m in dialog.messages:
            if m.role == "user":
                last_user = m
        intent = (last_user.content or "").lower() if last_user else ""

        state["step"] += 1
        # Second visit → always finish to keep the loop bounded.
        if state["step"] >= 2:
            return AssistantMessage(content="", tool_calls=[
                ToolCall(id=f"c{state['step']}", name="finish",
                          arguments={"summary": "Task completed."}),
            ])

        tc = _route_first_visit(intent)
        return AssistantMessage(content="", tool_calls=[tc])

    def reset() -> None:
        state["step"] = 0

    responder.reset = reset  # type: ignore[attr-defined]
    return responder
