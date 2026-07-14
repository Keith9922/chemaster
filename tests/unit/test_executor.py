"""tests/unit/test_executor.py"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from chemaster.agent.confirmation import ApprovedPlan
from chemaster.agent.executor import Executor
from chemaster.agent.plan import (
    McpCall,
    Plan,
    PlanStep,
    System,
)


@pytest.fixture
def tmp_runs(tmp_path):
    """返回一个临时 runs 目录，测试结束后自动清理。"""
    runs = tmp_path / "runs"
    runs.mkdir()
    yield runs
    # shutil.rmtree(tmp_path)  # pytest 自动清理


@pytest.fixture
def mock_const_fn():
    """mock chem.const 的 get_constant 函数。"""
    fn = MagicMock()
    fn._mcp_tool = True
    return fn


@pytest.fixture
def mock_psi4_optimize():
    """mock chem.calc_psi4 的 optimize 函数。"""
    fn = MagicMock()
    fn._mcp_tool = True
    return fn


@pytest.fixture
def mock_psi4_frequency():
    """mock chem.calc_psi4 的 frequency 函数。"""
    fn = MagicMock()
    fn._mcp_tool = True
    return fn


def make_approved_plan(steps: list[PlanStep], task_id: str = "task-test01") -> ApprovedPlan:
    """构造一个 confirm_token 非空的 ApprovedPlan。"""
    plan = Plan(
        task_id=task_id,
        user_intent="计算 H2O 能量",
        inferred_workflow="opt+freq",
        target_system=System(formula="H2O"),
        steps=steps,
    )
    return ApprovedPlan(plan=plan, confirm_token="token-abc123", user_edits=[])


class TestCreatesTaskDir:
    def test(self, tmp_runs):
        mock_opt = MagicMock()
        mock_opt._mcp_tool = True
        mock_opt.return_value = {
            "ok": True,
            "result": {"optimized_geometry_xyz": "H 0 0 0\nO 1 0 0\n"},
            "warnings": [],
            "meta": {},
        }

        plan = Plan(
            task_id="h2o-opt-test",
            user_intent="",
            inferred_workflow="",
            target_system=System(formula="H2O"),
            steps=[
                PlanStep(
                    name="geometry_optimization",
                    mcp_calls=[
                        McpCall(server="chem.calc.psi4", tool="optimize", args={"geometry_xyz": "H 0 0 0\nO 1 0 0\n"}),
                    ],
                ),
            ],
        )
        approved = ApprovedPlan(plan=plan, confirm_token="tok", user_edits=[])

        with patch.object(Executor, "_wire_mcps", lambda self: None):
            executor = Executor(runs_dir=tmp_runs)
            executor._mcp_funcs = {
                "calc_psi4": {"optimize": mock_opt},
            }

            result = executor.run(approved)

        assert result["ok"] is True
        assert (tmp_runs / "h2o-opt-test").exists()


class TestWritesMetaAndPlan:
    def test(self, tmp_runs):
        mock_get = MagicMock()
        mock_get._mcp_tool = True
        mock_get.return_value = {
            "ok": True,
            "value": 1.0,
            "unit": "Hartree",
            "warnings": [],
            "meta": {},
        }

        plan = Plan(
            task_id="meta-plan-test",
            user_intent="测试 meta + plan",
            inferred_workflow="single_point",
            target_system=System(formula="H2"),
            steps=[
                PlanStep(
                    name="single_point_energy",
                    mcp_calls=[
                        McpCall(
                            server="chem.const",
                            tool="get_constant",
                            args={"name": "hartree"},
                        ),
                    ],
                ),
            ],
        )
        approved = ApprovedPlan(plan=plan, confirm_token="tok", user_edits=[])

        with patch.object(Executor, "_wire_mcps", lambda self: None):
            executor = Executor(runs_dir=tmp_runs)
            executor._mcp_funcs = {
                "const": {"get_constant": mock_get},
            }

            executor.run(approved)

        task_dir = tmp_runs / "meta-plan-test"
        meta_path = task_dir / "meta.json"
        plan_path = task_dir / "plan.json"

        assert meta_path.exists()
        assert plan_path.exists()

        meta = json.loads(meta_path.read_text())
        assert "timestamp" in meta
        assert "python_version" in meta

        plan_loaded = json.loads(plan_path.read_text())
        assert plan_loaded["task_id"] == "meta-plan-test"
        assert plan_loaded["user_intent"] == "测试 meta + plan"


class TestStepDirsCreated:
    def test(self, tmp_runs):
        mock_opt = MagicMock()
        mock_opt._mcp_tool = True
        mock_opt.return_value = {
            "ok": True,
            "result": {"optimized_geometry_xyz": "H 0 0 0\nO 1 0 0\n"},
            "warnings": [],
            "meta": {},
        }

        mock_freq = MagicMock()
        mock_freq._mcp_tool = True
        mock_freq.return_value = {
            "ok": True,
            "result": {},
            "warnings": [],
            "meta": {},
        }

        plan = Plan(
            task_id="step-dirs-test",
            user_intent="",
            inferred_workflow="",
            target_system=System(),
            steps=[
                PlanStep(
                    name="geometry_optimization",
                    mcp_calls=[
                        McpCall(server="chem.calc.psi4", tool="optimize", args={}),
                    ],
                ),
                PlanStep(
                    name="frequency_calculation",
                    mcp_calls=[
                        McpCall(server="chem.calc.psi4", tool="frequency", args={}),
                    ],
                ),
            ],
        )
        approved = ApprovedPlan(plan=plan, confirm_token="tok", user_edits=[])

        with patch.object(Executor, "_wire_mcps", lambda self: None):
            executor = Executor(runs_dir=tmp_runs)
            executor._mcp_funcs = {
                "calc_psi4": {
                    "optimize": mock_opt,
                    "frequency": mock_freq,
                },
            }
            executor.run(approved)

        task_dir = tmp_runs / "step-dirs-test"
        assert (task_dir / "step_01_geometry_optimization").exists()
        assert (task_dir / "step_02_frequency_calculation").exists()


class TestGeometryPassing:
    def test(self, tmp_runs, mock_psi4_optimize, mock_psi4_frequency):
        """step1 返回 optimized_geometry_xyz，step2 的 geometry_xyz 应被自动注入。"""
        geom_output = "H 0 0 0\nO 1 0 0\n"
        mock_psi4_optimize.return_value = {
            "ok": True,
            "result": {"optimized_geometry_xyz": geom_output},
            "warnings": [],
            "meta": {},
        }
        mock_psi4_frequency.return_value = {
            "ok": True,
            "result": {},
            "warnings": [],
            "meta": {},
        }

        plan = Plan(
            task_id="geo-pass-test",
            user_intent="",
            inferred_workflow="",
            target_system=System(),
            steps=[
                PlanStep(
                    name="geometry_optimization",
                    mcp_calls=[
                        McpCall(server="chem.calc.psi4", tool="optimize", args={}),
                    ],
                ),
                PlanStep(
                    name="frequency_calculation",
                    mcp_calls=[
                        # 注意：此处不传 geometry_xyz，期望自动从 step1 注入
                        McpCall(server="chem.calc.psi4", tool="frequency", args={}),
                    ],
                ),
            ],
        )
        approved = ApprovedPlan(plan=plan, confirm_token="tok", user_edits=[])

        with patch.object(Executor, "_wire_mcps", lambda self: None):
            executor = Executor(runs_dir=tmp_runs)
            executor._mcp_funcs = {
                "calc_psi4": {
                    "optimize": mock_psi4_optimize,
                    "frequency": mock_psi4_frequency,
                },
            }
            executor.run(approved)

        # frequency 被调用时，geometry_xyz 应被自动填入 step1 的返回值
        freq_call_args = mock_psi4_frequency.call_args
        assert freq_call_args is not None
        _, kwargs = freq_call_args
        assert kwargs.get("geometry_xyz") == geom_output


class TestStopsOnError:
    def test(self, tmp_runs, mock_psi4_optimize, mock_psi4_frequency):
        """step1 返回 ok=False，step2 不应被调用。"""
        mock_psi4_optimize.return_value = {
            "ok": False,
            "error_code": "SCF_NOT_CONVERGED",
            "suggestion": "try GWH guess",
            "warnings": [],
            "meta": {},
        }
        mock_psi4_frequency.return_value = MagicMock()  # 若被调用会失败

        plan = Plan(
            task_id="stop-on-error-test",
            user_intent="",
            inferred_workflow="",
            target_system=System(),
            steps=[
                PlanStep(
                    name="geometry_optimization",
                    mcp_calls=[
                        McpCall(server="chem.calc.psi4", tool="optimize", args={}),
                    ],
                ),
                PlanStep(
                    name="frequency_calculation",
                    mcp_calls=[
                        McpCall(server="chem.calc.psi4", tool="frequency", args={}),
                    ],
                ),
            ],
        )
        approved = ApprovedPlan(plan=plan, confirm_token="tok", user_edits=[])

        with patch.object(Executor, "_wire_mcps", lambda self: None):
            executor = Executor(runs_dir=tmp_runs)
            executor._mcp_funcs = {
                "calc_psi4": {
                    "optimize": mock_psi4_optimize,
                    "frequency": mock_psi4_frequency,
                },
            }
            result = executor.run(approved)

        assert result["ok"] is False
        assert result["n_steps_completed"] == 0
        mock_psi4_frequency.assert_not_called()


class TestRejectsNoToken:
    def test(self, tmp_runs):
        plan = Plan(
            task_id="no-token-test",
            user_intent="",
            inferred_workflow="",
            target_system=System(),
            steps=[],
        )
        # confirm_token 为空
        approved = ApprovedPlan(plan=plan, confirm_token="", user_edits=[])

        with patch.object(Executor, "_wire_mcps", lambda self: None):
            executor = Executor(runs_dir=tmp_runs)
            with pytest.raises(ValueError, match="confirm_token"):
                executor.run(approved)
