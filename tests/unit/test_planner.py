"""Planner Phase 1 硬编码 demo 测试。"""
from __future__ import annotations

import pytest

from chemaster.agent.planner import Planner


@pytest.fixture
def planner():
    return Planner()


def test_h2o_recognized(planner):
    plan = planner.create_plan("算 H2O 的能量")
    assert plan is not None
    assert plan.target_system.formula == "H2O"
    assert plan.inferred_workflow == "opt+freq"
    assert len(plan.steps) == 2


def test_h2o_alias_water(planner):
    plan = planner.create_plan("compute water energy")
    assert plan.target_system.formula == "H2O"


def test_h2o_alias_chinese(planner):
    plan = planner.create_plan("算水分子能量")
    assert plan.target_system.formula == "H2O"


def test_steps_structure(planner):
    plan = planner.create_plan("算 H2O 的能量")
    assert len(plan.steps) == 2

    step1 = plan.steps[0]
    assert step1.name == "geometry_optimization"
    assert step1.skill == "opt-freq"
    assert len(step1.mcp_calls) == 2
    assert step1.mcp_calls[0].server == "chem.io.ase"
    assert step1.mcp_calls[0].tool == "lookup_by_name"
    assert step1.mcp_calls[1].server == "chem.calc.psi4"
    assert step1.mcp_calls[1].tool == "optimize"

    step2 = plan.steps[1]
    assert step2.name == "frequency"
    assert step2.skill == "opt-freq"
    assert len(step2.mcp_calls) == 1
    assert step2.mcp_calls[0].server == "chem.calc.psi4"
    assert step2.mcp_calls[0].tool == "frequency"


def test_serializable(planner):
    plan = planner.create_plan("算 H2O 的能量")
    json_str = plan.to_json()
    assert "H2O" in json_str
    assert "opt+freq" in json_str


def test_unsupported(planner):
    with pytest.raises(NotImplementedError, match="Phase 1 only supports H2O"):
        planner.create_plan("optimize benzene")


def test_citations_not_empty(planner):
    plan = planner.create_plan("算 H2O 的能量")
    assert len(plan.citations) >= 1
    assert "B3LYP-D3(BJ)" in plan.citations[0].text


def test_cost_estimate(planner):
    plan = planner.create_plan("算 H2O 的能量")
    assert plan.total_estimate.cpu_minutes == 2.0
    assert plan.total_estimate.wall_clock_s == 120.0
