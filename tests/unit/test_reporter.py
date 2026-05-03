"""Markdown 报告生成器测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chemaster.agent.reporter import generate_report


def _write(p: Path, obj: dict) -> None:
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.fixture
def fake_task_dir(tmp_path: Path) -> Path:
    """构造一个完整的 H2O opt+freq 任务产物目录。"""
    td = tmp_path / "task-h2o-test"
    td.mkdir()

    plan = {
        "task_id": "task-h2o-test",
        "created_at": "2026-04-28T00:00:00+00:00",
        "user_intent": "算 H2O 的能量",
        "inferred_workflow": "opt+freq",
        "target_system": {
            "formula": "H2O",
            "smiles": "O",
            "charge": 0,
            "multiplicity": 1,
            "n_atoms": 3,
            "geometry_xyz": "3\nO 0 0 0\nH 0.96 0 0\nH -0.48 0.83 0\n",
        },
        "steps": [
            {
                "name": "geometry_optimization",
                "skill": "opt-freq",
                "rationale": "极小点搜索",
                "estimated_cost": {"wall_clock_s": 60.0},
                "alternatives": [],
                "mcp_calls": [],
                "risks": [],
            },
            {
                "name": "frequency",
                "skill": "opt-freq",
                "rationale": "确认极小点 + ZPE",
                "estimated_cost": {"wall_clock_s": 60.0},
                "alternatives": [],
                "mcp_calls": [],
                "risks": [],
            },
        ],
        "citations": [
            {
                "text": "B3LYP-D3(BJ) recommended for small organics",
                "source": "kb/rules/functionals.yaml#B3LYP-D3(BJ)",
                "score": 0.95,
            }
        ],
        "total_estimate": {"cpu_minutes": 2, "wall_clock_s": 120},
        "requires_confirmation": True,
    }
    _write(td / "plan.json", plan)
    _write(td / "meta.json", {
        "chemaster_version": "0.1.0",
        "python_version": "Python 3.11.7",
        "git_commit": "abc123def456",
        "timestamp": "2026-04-28T00:00:00Z",
    })

    step1 = td / "step_01_geometry_optimization"
    step1.mkdir()
    _write(step1 / "result.json", {
        "ok": True,
        "result": {
            "final_energy": {"value": -76.4636, "unit": "Hartree"},
            "optimized_geometry_xyz": "3\nO 0 0 0.117\nH 0 0.757 -0.470\nH 0 -0.757 -0.470\n",
            "n_iterations": 12,
            "converged": True,
        },
        "warnings": [],
        "meta": {"psi4_version": "1.10", "wall_time_s": 12.3,
                 "output_path": "/tmp/x"},
    })
    _write(step1 / "warnings.json", {"warnings": []})

    step2 = td / "step_02_frequency"
    step2.mkdir()
    _write(step2 / "result.json", {
        "ok": True,
        "result": {
            "frequencies_cm_inv": [1617.0, 3786.0, 3891.0],
            "ir_intensities_km_per_mol": [60.0, 4.0, 32.0],
            "n_imaginary": 0,
            "zpe": {"value": 0.02118, "unit": "Hartree"},
            "thermal_corrections": {
                "h_corr": {"value": 0.02408, "unit": "Hartree"},
                "g_corr": {"value": 0.00263, "unit": "Hartree"},
                "ts": {"value": 0.02145, "unit": "Hartree"},
                "method": "ASE-IdealGasThermo",
            },
            "temperature_K": 298.15,
            "pressure_atm": 1.0,
        },
        "warnings": [],
        "meta": {"psi4_version": "1.10", "wall_time_s": 8.1,
                 "output_path": "/tmp/y"},
    })
    _write(step2 / "warnings.json", {"warnings": []})

    return td


def test_generate_report_creates_md(fake_task_dir):
    out = generate_report(fake_task_dir)
    assert out.exists()
    assert out.name == "report.md"


def test_report_contains_key_sections(fake_task_dir):
    out = generate_report(fake_task_dir)
    md = out.read_text(encoding="utf-8")
    # 6 个 section
    assert "## 1. Target system" in md
    assert "## 2. Plan summary" in md
    assert "## 3. Step-by-step results" in md
    assert "## 4. Key results" in md
    assert "## 5. Citations" in md
    assert "## 6. Reproducibility" in md
    # task id
    assert "task-h2o-test" in md
    # 用户 intent
    assert "算 H2O 的能量" in md


def test_report_renders_energy_in_three_units(fake_task_dir):
    md = generate_report(fake_task_dir).read_text(encoding="utf-8")
    assert "Hartree" in md
    assert "kcal/mol" in md
    assert "eV" in md
    # 数值（不锁精度，用近似）
    assert "-76.463" in md or "-76.4636" in md


def test_report_renders_frequencies_table(fake_task_dir):
    md = generate_report(fake_task_dir).read_text(encoding="utf-8")
    assert "1617" in md
    assert "3786" in md
    assert "3891" in md
    assert "ZPE" in md
    assert "G_corr" in md


def test_report_marks_zero_imaginary(fake_task_dir):
    md = generate_report(fake_task_dir).read_text(encoding="utf-8")
    assert "imaginary frequencies" in md.lower()
    assert "0 ✓" in md or "**0**" in md


def test_report_renders_citations(fake_task_dir):
    md = generate_report(fake_task_dir).read_text(encoding="utf-8")
    assert "B3LYP-D3(BJ) recommended" in md
    assert "functionals.yaml#B3LYP-D3(BJ)" in md


def test_report_renders_failed_step(tmp_path):
    """失败的 step 也要渲染（错误码 + suggestion）。"""
    td = tmp_path / "fail-task"
    td.mkdir()
    _write(td / "plan.json", {
        "task_id": "fail-task",
        "user_intent": "test",
        "inferred_workflow": "opt+freq",
        "target_system": {"formula": "X"},
        "steps": [
            {"name": "opt", "rationale": "x",
             "estimated_cost": {}, "alternatives": [],
             "mcp_calls": [], "risks": []}
        ],
        "citations": [],
        "total_estimate": {}, "created_at": "x",
        "requires_confirmation": True,
    })
    _write(td / "meta.json", {})
    s = td / "step_01_opt"
    s.mkdir()
    _write(s / "result.json", {
        "ok": False,
        "error_code": "SCF_NOT_CONVERGED",
        "details": "diverged",
        "suggestion": "try GWH",
    })
    _write(s / "warnings.json", {"warnings": []})

    md = generate_report(td).read_text(encoding="utf-8")
    assert "SCF_NOT_CONVERGED" in md
    assert "try GWH" in md
    assert "FAILED" in md


def test_missing_plan_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        generate_report(tmp_path)
