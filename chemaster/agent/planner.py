"""Planner — legacy hard-coded H2O Plan builder (V1 compatibility).

⚠️ **Deprecated path**. The V2 architecture replaces hard-coded Planning with a
real LLM tool-use loop (see `chemaster.agent.agent.ChemAgent`). This module
remains so the Phase-1 H2O end-to-end test continues to pass and so any
existing scripts that build a Plan via `Planner().create_plan(intent)` keep
working.

For new code use `ChemAgent` + `build_default_chem_agent()` instead.
"""

from __future__ import annotations

from chemaster.agent.plan import (
    Citation,
    Cost,
    McpCall,
    Plan,
    PlanStep,
    System,
)


class Planner:
    """Phase 1 硬编码 Planner —— 仅支持 H2O opt+freq。

    Phase 2 实现：
    1. retriever.search(user_intent) → 找匹配 skill + KB 规则
    2. LLM 出 Plan 草案
    3. 校验：成本爆炸、不支持元素、单位异常
    4. 输出最终 Plan
    """

    _H2O_KEYWORDS = ["h2o", "水分子", "water"]
    _DEFAULT_METHOD = "B3LYP-D3(BJ)"
    _DEFAULT_BASIS = "def2-TZVP"

    def __init__(self, llm_client=None, retriever=None) -> None:
        self.llm = llm_client
        self.retriever = retriever

    def create_plan(self, user_intent: str) -> Plan:
        text = user_intent.lower().strip()
        if any(kw in text for kw in self._H2O_KEYWORDS):
            return self._h2o_opt_freq_plan(user_intent)
        raise NotImplementedError(
            f"Phase 1 only supports H2O. Got: {user_intent!r}"
        )

    def _h2o_opt_freq_plan(self, user_intent: str) -> Plan:
        target_system = System(
            formula="H2O",
            smiles="O",
            charge=0,
            multiplicity=1,
            n_atoms=3,
            notes="neutral singlet water",
        )

        step1 = PlanStep(
            name="geometry_optimization",
            skill="opt-freq",
            mcp_calls=[
                McpCall(
                    server="chem.io.ase",
                    tool="lookup_by_name",
                    args={"name": "water"},
                ),
                McpCall(
                    server="chem.calc.psi4",
                    tool="optimize",
                    args={
                        "method": self._DEFAULT_METHOD,
                        "basis": self._DEFAULT_BASIS,
                        "charge": 0,
                        "multiplicity": 1,
                    },
                ),
            ],
            rationale="获取优化几何，作为频率计算起点",
            estimated_cost=Cost(
                cpu_minutes=1.0,
                memory_gb=1.0,
                wall_clock_s=60.0,
                confidence="high",
            ),
            risks=["SCF_NOT_CONVERGED", "GEOMETRY_NOT_CONVERGED"],
        )

        step2 = PlanStep(
            name="frequency",
            skill="opt-freq",
            mcp_calls=[
                McpCall(
                    server="chem.calc.psi4",
                    tool="frequency",
                    args={
                        "method": self._DEFAULT_METHOD,
                        "basis": self._DEFAULT_BASIS,
                        "charge": 0,
                        "multiplicity": 1,
                    },
                ),
            ],
            rationale="验证极小点，获取 ZPE 和热力学修正",
            estimated_cost=Cost(
                cpu_minutes=1.0,
                memory_gb=1.0,
                wall_clock_s=60.0,
                confidence="high",
            ),
            risks=["NEGATIVE_FREQUENCIES"],
        )

        return Plan(
            user_intent=user_intent,
            inferred_workflow="opt+freq",
            target_system=target_system,
            steps=[step1, step2],
            total_estimate=Cost(
                cpu_minutes=2.0,
                memory_gb=2.0,
                wall_clock_s=120.0,
                confidence="high",
            ),
            citations=[
                Citation(
                    text="B3LYP-D3(BJ) with def2-TZVP recommended for small organic molecules",
                    source="kb/rules/functionals.yaml#B3LYP-D3(BJ)",
                    score=0.95,
                )
            ],
            requires_confirmation=True,
        )
