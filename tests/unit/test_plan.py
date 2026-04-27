"""Plan 数据类序列化测试。"""

from __future__ import annotations

import json

from chemaster.agent.plan import (
    Alternative,
    Citation,
    Cost,
    McpCall,
    Plan,
    PlanStep,
    System,
)


def make_sample_plan() -> Plan:
    return Plan(
        user_intent="算 H2O 的能量",
        inferred_workflow="opt+freq",
        target_system=System(formula="H2O", charge=0, multiplicity=1, n_atoms=3),
        steps=[
            PlanStep(
                name="geometry_optimization",
                skill="opt-freq",
                mcp_calls=[
                    McpCall(
                        server="chem.calc.psi4",
                        tool="optimize",
                        args={"method": "B3LYP-D3(BJ)", "basis": "def2-TZVP"},
                    )
                ],
                rationale="小分子默认精度-成本平衡点",
                alternatives=[Alternative(label="ωB97X-D / def2-TZVP", rationale="更准但 +30%")],
                estimated_cost=Cost(cpu_minutes=0.5, memory_gb=1.0),
                risks=[],
            )
        ],
        total_estimate=Cost(cpu_minutes=1, memory_gb=1, wall_clock_s=60),
        citations=[Citation(text="B3LYP 推荐", source="kb/rules/functionals.yaml#b3lyp")],
    )


def test_plan_roundtrip(tmp_path):
    p = make_sample_plan()
    path = tmp_path / "plan.json"
    p.save(path)
    p2 = Plan.load(path)
    assert p2.user_intent == p.user_intent
    assert p2.steps[0].mcp_calls[0].tool == "optimize"
    assert p2.target_system.formula == "H2O"


def test_plan_json_is_utf8_friendly():
    p = make_sample_plan()
    s = p.to_json()
    assert "算 H2O 的能量" in s
    assert json.loads(s)["inferred_workflow"] == "opt+freq"


def test_task_id_unique():
    a = Plan()
    b = Plan()
    assert a.task_id != b.task_id
