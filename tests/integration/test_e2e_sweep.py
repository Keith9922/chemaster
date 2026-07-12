"""Comprehensive end-to-end agent sweep across multiple small molecules.

This is the *final E2E gate* for architecture V2. For every supported
molecule in the lookup table we:

  1. Spin up a fresh ChemAgent with simulated_chemist responder
     (mocked LLM, real psi4).
  2. Drive the full opt+freq pipeline.
  3. Assert:
     - Trajectory completes ('completed' status)
     - Final electronic energy lands in a reasonable range for B3LYP-D3(BJ)/def2-SVP
     - Number of vibrational frequencies = 3N-6 (or 3N-5 for linear)
     - Zero imaginary frequencies for a true minimum
  4. Aggregate results, write a Markdown report to
     ``runs/_e2e_sweep_report.md`` for the user.

These tests are heavy (real DFT). Marked `@integration`; opt-in via
``pytest -m integration``.

Reference points used:
- Energies: rough literature values for B3LYP-class/def2-SVP electronic
  energy (well within 0.5 Hartree of reality).
- Mode counts: 3N-6 (non-linear) or 3N-5 (linear).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import pytest

from chemaster.agent.agent import AgentConfig, ChemAgent
from chemaster.agent.llm_client import (
    MockLLM,
    stub_assistant_message,
    stub_tool_call,
)
from chemaster.agent.tool_loader import build_default_registry
from chemaster.agent.types import (
    AssistantMessage,
    Dialog,
    TaskInstance,
    ToolMessage,
)

# ──────────────────────────────────────────────────────────────────────────
# Sweep configuration
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def sweep_target_dir(tmp_path_factory) -> Path:
    """Single shared runs directory for the whole sweep."""
    d = tmp_path_factory.mktemp("e2e_sweep")
    return d


_CORE_MOLECULES: list[dict[str, Any]] = [
    # name, expected_n_modes, expected_energy_range_Hartree, n_atoms, linear
    {
        "name": "water",
        "n_atoms": 3,
        "n_modes": 3,                       # 3N-6 = 3
        "energy_range": (-76.50, -76.20),
        "linear": False,
    },
    {
        "name": "methane",
        "n_atoms": 5,
        "n_modes": 9,                       # 3N-6 = 9
        "energy_range": (-40.55, -40.30),
        "linear": False,
    },
    {
        "name": "ammonia",
        "n_atoms": 4,
        "n_modes": 6,                       # 3N-6 = 6
        "energy_range": (-56.55, -56.30),
        "linear": False,
    },
    {
        "name": "co2",
        "n_atoms": 3,
        "n_modes": 4,                       # 3N-5 = 4 (linear)
        "energy_range": (-188.55, -188.20),
        "linear": True,
    },
]

# Heavier molecules — opt-in via env flag to keep routine sweep ≤ 2 min.
_FULL_MOLECULES: list[dict[str, Any]] = [
    {
        "name": "ethanol",
        "n_atoms": 9,
        "n_modes": 21,                      # 3N-6 = 21
        # B3LYP-D3(BJ)/def2-SVP gives ~ -154.92 H. Widened to allow ±0.05.
        "energy_range": (-155.00, -154.80),
        "linear": False,
    },
]

SWEEP_MOLECULES = list(_CORE_MOLECULES)
if os.environ.get("CHEMASTER_E2E_FULL"):
    SWEEP_MOLECULES.extend(_FULL_MOLECULES)


# ──────────────────────────────────────────────────────────────────────────
# Simulated chemist (re-used pattern from test_agent_real_psi4.py)
# ──────────────────────────────────────────────────────────────────────────


def _last_tool(dialog: Dialog) -> tuple[str | None, dict | None]:
    for m in reversed(dialog.messages):
        if isinstance(m, ToolMessage):
            return m.name, (m.meta or {}).get("data")
    return None, None


def make_simulated_chemist(target: str):
    state = {
        "step": 0, "xyz": None, "optimized_xyz": None,
        "energy": None, "freqs": None, "n_imag": 0,
    }

    def respond(dialog: Dialog) -> AssistantMessage:
        name, data = _last_tool(dialog)
        if name == "io_lookup_by_name" and data:
            state["xyz"] = (data.get("result") or {}).get("xyz")
            state["step"] = 1
        elif name == "calc_psi4_optimize" and data:
            r = data.get("result") or {}
            state["optimized_xyz"] = r.get("optimized_geometry_xyz") or r.get("xyz")
            state["energy"] = (r.get("final_energy") or {}).get("value")
            state["step"] = 2
        elif name == "calc_psi4_frequency" and data:
            r = data.get("result") or {}
            state["freqs"] = r.get("frequencies_cm_inv") or []
            state["n_imag"] = sum(1 for f in state["freqs"] if f < -10.0)
            state["step"] = 3

        if state["step"] == 0:
            return stub_assistant_message(
                f"Looking up {target}.",
                [stub_tool_call("io_lookup_by_name", {"name": target})],
            )
        if state["step"] == 1:
            return stub_assistant_message(
                "Optimizing geometry.",
                [stub_tool_call("calc_psi4_optimize", {
                    "geometry_xyz": state["xyz"],
                    "method": "B3LYP-D3(BJ)",
                    "basis": "def2-SVP",
                    "charge": 0,
                    "multiplicity": 1,
                })],
            )
        if state["step"] == 2:
            return stub_assistant_message(
                "Frequencies.",
                [stub_tool_call("calc_psi4_frequency", {
                    "geometry_xyz": state["optimized_xyz"],
                    "method": "B3LYP-D3(BJ)",
                    "basis": "def2-SVP",
                    "charge": 0,
                    "multiplicity": 1,
                })],
            )
        return stub_assistant_message(
            "done",
            [stub_tool_call("finish", {
                "summary": (
                    f"{target}: B3LYP-D3(BJ)/def2-SVP, "
                    f"E={state['energy']} Hartree, "
                    f"{len(state['freqs'])} modes, n_imag={state['n_imag']}."
                ),
                "key_results": {
                    "molecule": target,
                    "method": "B3LYP-D3(BJ)/def2-SVP",
                    "final_energy_Hartree": state["energy"],
                    "n_frequencies": len(state["freqs"] or []),
                    "n_imaginary": state["n_imag"],
                },
            })],
        )

    return respond, state


# ──────────────────────────────────────────────────────────────────────────
# Per-molecule test
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.parametrize("spec", SWEEP_MOLECULES, ids=lambda s: s["name"])
def test_e2e_sweep_one_molecule(spec, sweep_target_dir: Path) -> None:
    """One molecule end-to-end with mocked LLM and real psi4."""
    target = spec["name"]
    responder, state = make_simulated_chemist(target)
    llm = MockLLM(responder=responder)
    registry = build_default_registry()
    cfg = AgentConfig(
        max_turns=10,
        runs_dir=sweep_target_dir,
        confirm_callback=lambda *_: True,
    )
    agent = ChemAgent(llm=llm, tools=registry, config=cfg)

    t0 = time.time()
    traj = agent.run(TaskInstance(
        description=f"Compute the energy of {target}.",
        task_id=f"sweep-{target}",
    ))
    elapsed = time.time() - t0

    # Always record the result (success or failure) for the aggregated report.
    result_record = {
        "molecule": target,
        "status": traj.status,
        "wall_time_s": round(elapsed, 1),
        "final_energy": state["energy"],
        "n_frequencies": len(state["freqs"] or []),
        "n_imaginary": state["n_imag"],
        "expected_energy_range": spec["energy_range"],
        "expected_n_modes": spec["n_modes"],
    }
    _record_sweep_result(sweep_target_dir, result_record)

    assert traj.status == "completed", (
        f"{target}: trajectory not completed: {traj.finish_payload}"
    )
    assert state["energy"] is not None, f"{target}: agent never extracted energy"

    e_min, e_max = spec["energy_range"]
    assert e_min < state["energy"] < e_max, (
        f"{target}: energy {state['energy']} outside ({e_min}, {e_max})"
    )

    assert len(state["freqs"]) == spec["n_modes"], (
        f"{target}: got {len(state['freqs'])} modes, expected {spec['n_modes']}"
    )
    assert state["n_imag"] == 0, (
        f"{target}: unexpected imaginary frequencies {state['freqs']}"
    )


# ──────────────────────────────────────────────────────────────────────────
# Aggregation hook — runs after the parametrized sweep finishes
# ──────────────────────────────────────────────────────────────────────────


def _record_sweep_result(runs_dir: Path, record: dict) -> None:
    """Append one row to runs_dir/_e2e_sweep_results.jsonl."""
    out = runs_dir / "_e2e_sweep_results.jsonl"
    with out.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")


@pytest.mark.integration
def test_e2e_sweep_summary_report(sweep_target_dir: Path) -> None:
    """After the sweep, write a Markdown summary report.

    Depends on test_e2e_sweep_one_molecule having run; if pytest is run
    with --collect-only or selectively, this just produces an empty report.
    """
    results_path = sweep_target_dir / "_e2e_sweep_results.jsonl"
    if not results_path.exists():
        pytest.skip("Sweep results file not present (sweep didn't run).")

    rows = [json.loads(line) for line in results_path.read_text().splitlines() if line.strip()]
    n_total = len(rows)
    n_pass = sum(1 for r in rows if r["status"] == "completed")
    total_wall = sum(r["wall_time_s"] for r in rows)

    report_lines = [
        "# ChemMaster V2 — End-to-End Agent Sweep Report",
        "",
        f"Total molecules: {n_total}",
        f"Passed: {n_pass} / {n_total}",
        f"Total wall time: {total_wall:.1f} s",
        "",
        "| molecule | status | E (Hartree) | n_modes | n_imag | wall (s) |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        e_str = f"{r['final_energy']:.4f}" if r["final_energy"] is not None else "n/a"
        report_lines.append(
            f"| {r['molecule']} | {r['status']} | {e_str} "
            f"| {r['n_frequencies']} | {r['n_imaginary']} | {r['wall_time_s']} |"
        )

    report = "\n".join(report_lines) + "\n"
    out = sweep_target_dir / "_e2e_sweep_report.md"
    out.write_text(report, encoding="utf-8")
    print("\n" + report)

    assert n_pass == n_total, f"sweep had failures: {n_total - n_pass}"
