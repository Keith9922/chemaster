"""H2O 端到端集成测试 —— Phase 1 MVP 验收。

真跑 psi4（B3LYP-D3(BJ)/def2-TZVP），验证：
1. Planner → Confirmation → Executor 三段式串联正确
2. 能量数值在经验范围内（-76.5 ~ -76.3 Hartree）
3. 频率无虚频，3 个频率均 > 1500 cm⁻¹
4. 全流程 < 5 分钟（CLAUDE.md §3 #1 硬指标）

运行：pytest tests/integration/test_h2o_e2e.py -v -m integration --tb=short
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from chemaster.agent.confirmation import ApprovedPlan
from chemaster.agent.executor import Executor
from chemaster.agent.planner import Planner


@pytest.mark.integration
def test_h2o_end_to_end(tmp_runs_dir: Path) -> None:
    """完整端到端：用户说"算 H2O 的能量" → 产出 report 含正确能量。"""
    # 1. Planner
    plan = Planner().create_plan("算 H2O 的能量")
    assert plan.target_system.formula == "H2O"
    assert len(plan.steps) == 2

    # 2. Confirmation 简化（本测试跳过用户交互，直接造 ApprovedPlan）
    approved = ApprovedPlan(plan=plan, confirm_token="test-token", user_edits=[])

    # 3. Executor
    executor = Executor(runs_dir=tmp_runs_dir)
    result = executor.run(approved)

    # 4. 顶层断言
    assert result["ok"], f"Executor returned ok=False: {result.get('warnings')}"
    assert result["n_steps_completed"] == 2

    # 5. 数值断言
    task_dir = Path(result["task_dir"])

    # Step 1：几何优化
    opt_result_path = task_dir / "step_01_geometry_optimization" / "result.json"
    assert opt_result_path.exists(), f"step 1 result.json not found: {opt_result_path}"
    opt_result = json.loads(opt_result_path.read_text())
    final_energy_Eh = opt_result["result"]["final_energy"]["value"]
    assert -76.5 < final_energy_Eh < -76.3, (
        f"H2O B3LYP-D3(BJ)/def2-TZVP energy {final_energy_Eh} Eh "
        f"outside expected range (-76.5, -76.3)"
    )

    # Step 2：频率计算
    freq_result_path = task_dir / "step_02_frequency" / "result.json"
    assert freq_result_path.exists(), f"step 2 result.json not found: {freq_result_path}"
    freq_result = json.loads(freq_result_path.read_text())
    assert freq_result["result"]["n_imaginary"] == 0, "H2O should have zero imaginary frequencies"

    freqs = freq_result["result"]["frequencies_cm_inv"]
    assert len(freqs) == 3, f"H2O should have 3N-6=3 vibrational modes, got {len(freqs)}"
    assert all(f > 1500 for f in freqs), (
        f"All H2O frequencies should be > 1500 cm⁻¹, got {freqs}"
    )


@pytest.mark.integration
def test_h2o_smoke_under_5min(tmp_runs_dir: Path) -> None:
    """硬指标：H2O 端到端 < 5 分钟（CLAUDE.md §3 #1）。"""
    t0 = time.time()

    plan = Planner().create_plan("算 H2O 的能量")
    approved = ApprovedPlan(plan=plan, confirm_token="smoke-token", user_edits=[])
    executor = Executor(runs_dir=tmp_runs_dir)
    result = executor.run(approved)

    elapsed = time.time() - t0
    assert elapsed < 300, f"H2O end-to-end took {elapsed:.1f}s, exceeds 5min budget"
    assert result["ok"], f"Executor returned ok=False: {result.get('warnings')}"
