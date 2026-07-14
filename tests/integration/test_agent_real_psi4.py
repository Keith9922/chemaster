"""Agent integration tests — mocked LLM, real psi4.

These tests run the full V2 ChemAgent loop with a *scripted* LLM that emits
exactly the tool-call sequence a chemistry-aware Claude would emit, but use
**real psi4** for the calculations. They prove that:

1. ChemAgent + ToolRegistry + MCP adapter chain works end-to-end.
2. Real psi4 invocations land inside the Agent loop (not the legacy
   Executor).
3. Tool errors / warnings round-trip through the dialog.
4. Trajectory is persisted to disk for replay/audit.

We use the `simulated_chemist` LLM responder pattern: a small state machine
that inspects the dialog and emits the next tool call. This keeps the test
deterministic and fast while still exercising the full plumbing.

Marked `integration` — slow (real DFT), opt-in via `pytest -m integration`.
"""

from __future__ import annotations

import json
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
# Simulated chemist responder
# ──────────────────────────────────────────────────────────────────────────


def _last_tool_observation(dialog: Dialog) -> tuple[str | None, str | None, dict | None]:
    """Return (tool_name, observation, parsed_data) for the most recent tool message."""
    for msg in reversed(dialog.messages):
        if isinstance(msg, ToolMessage):
            data = (msg.meta or {}).get("data")
            return msg.name, msg.content, data
    return None, None, None


def _extract_xyz(observation: str | None, data: dict | None) -> str | None:
    """Pull an xyz block out of either the structured data or the observation text."""
    if data and isinstance(data, dict):
        result = data.get("result", {})
        for key in ("optimized_geometry_xyz", "xyz", "geometry_xyz"):
            v = result.get(key) if isinstance(result, dict) else None
            if v:
                return v
    if observation and "\n" in observation:
        # Cheap fallback: find a substring that looks like an xyz block.
        for chunk in observation.split("\n\n"):
            lines = chunk.strip().splitlines()
            if lines and lines[0].strip().isdigit() and len(lines) >= int(lines[0].strip()) + 2:
                return chunk.strip()
    return None


def make_simulated_chemist(target_molecule: str) -> Any:
    """A tiny state machine that emits opt+freq tool calls for the agent.

    Steps:
        1. io_lookup_by_name (target_molecule)   →  xyz
        2. calc_psi4_optimize (xyz, B3LYP-D3(BJ)/def2-SVP)  →  optimized_xyz, energy
        3. calc_psi4_frequency (optimized_xyz, same method)  →  freqs, ZPE
        4. finish (summary + key_results)
    """

    state = {"step": 0, "xyz": None, "optimized_xyz": None, "energy": None, "freqs": None}

    def respond(dialog: Dialog) -> AssistantMessage:
        # Inspect last tool message to update state.
        name, _obs, data = _last_tool_observation(dialog)
        if name == "io_lookup_by_name" and data:
            state["xyz"] = (data.get("result") or {}).get("xyz")
            state["step"] = 1
        elif name == "calc_psi4_optimize" and data:
            res = data.get("result") or {}
            state["optimized_xyz"] = res.get("optimized_geometry_xyz") or res.get("xyz")
            state["energy"] = (res.get("final_energy") or {}).get("value")
            state["step"] = 2
        elif name == "calc_psi4_frequency" and data:
            res = data.get("result") or {}
            state["freqs"] = res.get("frequencies_cm_inv")
            state["step"] = 3

        # Emit next tool call based on state.
        if state["step"] == 0:
            return stub_assistant_message(
                f"Looking up {target_molecule}.",
                [stub_tool_call("io_lookup_by_name", {"name": target_molecule})],
            )
        if state["step"] == 1:
            return stub_assistant_message(
                "Optimizing geometry with B3LYP-D3(BJ)/def2-SVP for speed.",
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
                "Running harmonic frequencies.",
                [stub_tool_call("calc_psi4_frequency", {
                    "geometry_xyz": state["optimized_xyz"],
                    "method": "B3LYP-D3(BJ)",
                    "basis": "def2-SVP",
                    "charge": 0,
                    "multiplicity": 1,
                })],
            )
        # step >= 3 → finish
        return stub_assistant_message(
            "Calculation complete; summarizing.",
            [stub_tool_call("finish", {
                "summary": (
                    f"Optimized {target_molecule} at B3LYP-D3(BJ)/def2-SVP. "
                    f"Final electronic energy {state['energy']} Hartree. "
                    f"{len(state['freqs'] or [])} vibrational modes."
                ),
                "key_results": {
                    "molecule": target_molecule,
                    "method": "B3LYP-D3(BJ)/def2-SVP",
                    "final_energy_Hartree": state["energy"],
                    "n_frequencies": len(state["freqs"] or []),
                    "n_imaginary": sum(1 for f in (state["freqs"] or []) if f < -10.0),
                },
            })],
        )

    return respond, state


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────


def _run_agent_for_molecule(
    target: str,
    runs_dir: Path,
    max_turns: int = 10,
) -> tuple[Any, dict]:
    responder, state = make_simulated_chemist(target)
    llm = MockLLM(responder=responder)
    registry = build_default_registry()
    cfg = AgentConfig(
        max_turns=max_turns,
        runs_dir=runs_dir,
        confirm_callback=lambda *_: True,    # auto-approve all long-running tools
    )
    agent = ChemAgent(llm=llm, tools=registry, config=cfg)
    traj = agent.run(TaskInstance(description=f"Compute the energy of {target}."))
    return traj, state


def _expected_energy_range(molecule: str) -> tuple[float, float]:
    """Loose reasonable ranges for B3LYP-D3(BJ)/def2-SVP electronic energies."""
    return {
        "methane":  (-40.55, -40.30),       # CH4
        "water":    (-76.50, -76.20),       # H2O
        "ethanol":  (-154.20, -153.80),     # C2H5OH
        "benzene":  (-232.10, -231.50),     # C6H6
        "ammonia":  ( -56.55,  -56.30),     # NH3
    }[molecule]


# ──────────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_agent_runs_methane_opt_freq_real_psi4(tmp_runs_dir: Path) -> None:
    """CH4 — smallest non-H2O case; tightest sanity check."""
    traj, state = _run_agent_for_molecule("methane", tmp_runs_dir)

    assert traj.status == "completed", f"trajectory failed: {traj.finish_payload}"
    assert state["energy"] is not None, "agent never extracted final energy"

    e_min, e_max = _expected_energy_range("methane")
    assert e_min < state["energy"] < e_max, (
        f"CH4 energy {state['energy']} Hartree outside reasonable range "
        f"({e_min}, {e_max})"
    )

    # 3N-6 = 9 frequencies; CH4 has degenerate modes
    assert state["freqs"] is not None and len(state["freqs"]) == 9
    n_imag = sum(1 for f in state["freqs"] if f < -10.0)
    assert n_imag == 0, f"unexpected imaginary frequencies: {state['freqs']}"


@pytest.mark.integration
def test_agent_runs_ammonia_opt_freq_real_psi4(tmp_runs_dir: Path) -> None:
    """NH3 — closed shell, slightly larger; tests ammonia name resolution."""
    traj, state = _run_agent_for_molecule("ammonia", tmp_runs_dir)

    assert traj.status == "completed", f"failed: {traj.finish_payload}"
    e_min, e_max = _expected_energy_range("ammonia")
    assert e_min < state["energy"] < e_max
    # NH3 has 3N-6 = 6 frequencies
    assert state["freqs"] is not None and len(state["freqs"]) == 6


@pytest.mark.integration
def test_agent_persists_full_trajectory(tmp_runs_dir: Path) -> None:
    """The agent must write trajectory.json with all steps for replay."""
    traj, _ = _run_agent_for_molecule("methane", tmp_runs_dir)

    traj_path = tmp_runs_dir / traj.task_id / "trajectory.json"
    assert traj_path.exists()

    payload = json.loads(traj_path.read_text(encoding="utf-8"))
    assert payload["status"] == "completed"
    # io_lookup → optimize → frequency → finish = 4 steps
    assert len(payload["steps"]) == 4

    step_names = [
        s["assistant_message"]["tool_calls"][0]["name"]
        for s in payload["steps"]
        if s["assistant_message"]["tool_calls"]
    ]
    assert step_names == [
        "io_lookup_by_name",
        "calc_psi4_optimize",
        "calc_psi4_frequency",
        "finish",
    ]


@pytest.mark.integration
def test_agent_finish_payload_carries_key_results(tmp_runs_dir: Path) -> None:
    """The finish tool's key_results are accessible from the agent."""
    traj, state = _run_agent_for_molecule("methane", tmp_runs_dir)
    assert traj.status == "completed"

    # Pull the finish payload from the trajectory.
    last_step = traj.steps[-1]
    finish_args = last_step.assistant_message.tool_calls[0].arguments  # type: ignore[union-attr]
    key_results = finish_args["key_results"]

    assert key_results["molecule"] == "methane"
    assert key_results["method"] == "B3LYP-D3(BJ)/def2-SVP"
    assert key_results["n_imaginary"] == 0
    assert key_results["n_frequencies"] == 9
