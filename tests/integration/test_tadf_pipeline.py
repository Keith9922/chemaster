"""End-to-end TADF-style pipeline integration test.

Drives ChemAgent through the complete excited-state chain for a small
TADF-like molecule (benzene as smoke test; DMAC-BP as the opt-in real
TADF anchor):

    io_lookup_by_name → calc_psi4_optimize → calc_psi4_frequency
                     → calc_psi4_tddft     → finish

This validates the entire P0 stack (TDDFT + thermal corrections +
TADF anchor lookup) end-to-end with real psi4. It's the integration
counterpart to the V2 architecture's headline use case.

Marked `integration` (slow, real DFT). DMAC-BP is gated behind
CHEMASTER_E2E_FULL=1 because the real TADF anchor at 82 atoms takes
multiple hours.
"""

from __future__ import annotations

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


def _last_tool_data(dialog: Dialog) -> tuple[str | None, dict | None]:
    for m in reversed(dialog.messages):
        if isinstance(m, ToolMessage):
            return m.name, (m.meta or {}).get("data")
    return None, None


def _make_tadf_responder(target: str, basis: str = "STO-3G",
                        method: str = "B3LYP") -> tuple[Any, dict]:
    """Build a scripted LLM responder that walks the full TADF chain.

    Pipeline: lookup → optimize → frequency → tddft → finish.

    Uses STO-3G for routine smoke speed; bigger basis sets are an
    explicit caller choice.
    """
    state = {
        "step": 0, "xyz": None, "opt_xyz": None, "energy": None,
        "freqs": None, "n_imag": None, "h_corr": None, "g_corr": None,
        "delta_e_st": None, "s1": None, "t1": None, "f_s1": None,
    }

    def respond(dialog: Dialog) -> AssistantMessage:
        name, data = _last_tool_data(dialog)
        if name == "io_lookup_by_name" and data:
            state["xyz"] = (data.get("result") or {}).get("xyz")
            state["step"] = 1
        elif name == "calc_psi4_optimize" and data:
            r = data.get("result") or {}
            state["opt_xyz"] = r.get("optimized_geometry_xyz") or r.get("xyz")
            state["energy"] = (r.get("final_energy") or {}).get("value")
            state["step"] = 2
        elif name == "calc_psi4_frequency" and data:
            r = data.get("result") or {}
            state["freqs"] = r.get("frequencies_cm_inv")
            state["n_imag"] = r.get("n_imaginary")
            tc = r.get("thermal_corrections", {}) or {}
            state["h_corr"] = (tc.get("h_corr") or {}).get("value") if tc.get("h_corr") else None
            state["g_corr"] = (tc.get("g_corr") or {}).get("value") if tc.get("g_corr") else None
            state["step"] = 3
        elif name == "calc_psi4_tddft" and data:
            r = data.get("result") or {}
            singlets = r.get("singlets") or []
            triplets = r.get("triplets") or []
            if singlets:
                state["s1"] = singlets[0]["excitation_energy"]["value"]
                state["f_s1"] = singlets[0]["oscillator_strength"]
            if triplets:
                state["t1"] = triplets[0]["excitation_energy"]["value"]
            state["delta_e_st"] = r.get("delta_E_ST_eV")
            state["step"] = 4

        if state["step"] == 0:
            return stub_assistant_message(
                f"Looking up {target}.",
                [stub_tool_call("io_lookup_by_name", {"name": target})],
            )
        if state["step"] == 1:
            return stub_assistant_message(
                f"Optimizing geometry at {method}/{basis}.",
                [stub_tool_call("calc_psi4_optimize", {
                    "geometry_xyz": state["xyz"],
                    "method": method, "basis": basis,
                    "charge": 0, "multiplicity": 1,
                })],
            )
        if state["step"] == 2:
            return stub_assistant_message(
                "Computing harmonic frequencies + thermal corrections.",
                [stub_tool_call("calc_psi4_frequency", {
                    "geometry_xyz": state["opt_xyz"],
                    "method": method, "basis": basis,
                    "charge": 0, "multiplicity": 1,
                })],
            )
        if state["step"] == 3:
            return stub_assistant_message(
                "Running TDDFT for excited states (TDA, singlets + triplets).",
                [stub_tool_call("calc_psi4_tddft", {
                    "geometry_xyz": state["opt_xyz"],
                    "method": method, "basis": basis,
                    "charge": 0, "multiplicity": 1,
                    "n_states": 3, "triplets": True, "tda": True,
                })],
            )

        return stub_assistant_message(
            "Pipeline complete; summarizing.",
            [stub_tool_call("finish", {
                "summary": (
                    f"{target} TADF-style pipeline at {method}/{basis}: "
                    f"E_GS={state['energy']:.4f} H, "
                    f"S1={state['s1']} eV (f={state['f_s1']}), "
                    f"T1={state['t1']} eV, ΔE_ST={state['delta_e_st']} eV"
                ),
                "key_results": {
                    "molecule": target, "method": f"{method}/{basis}",
                    "ground_state_energy_Hartree": state["energy"],
                    "h_corr_Hartree": state["h_corr"],
                    "g_corr_Hartree": state["g_corr"],
                    "s1_eV": state["s1"], "t1_eV": state["t1"],
                    "delta_E_ST_eV": state["delta_e_st"],
                    "f_S1": state["f_s1"], "n_imaginary": state["n_imag"],
                },
            })],
        )

    return respond, state


def _run_tadf_pipeline(target: str, runs_dir: Path, *,
                      basis: str = "STO-3G", method: str = "B3LYP",
                      max_turns: int = 8) -> tuple[Any, dict]:
    responder, state = _make_tadf_responder(target, basis=basis, method=method)
    llm = MockLLM(responder=responder)
    registry = build_default_registry()
    cfg = AgentConfig(
        max_turns=max_turns, runs_dir=runs_dir,
        confirm_callback=lambda *_: True,
    )
    agent = ChemAgent(llm=llm, tools=registry, config=cfg)
    traj = agent.run(TaskInstance(
        description=f"Run TADF-style pipeline (opt → freq → TDDFT) on {target}.",
        task_id=f"tadf-{target.lower()}",
    ))
    return traj, state


# ──────────────────────────────────────────────────────────────────────────
# Routine smoke: benzene with STO-3G (cheap, ~30 s)
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_tadf_pipeline_smoke_benzene(tmp_runs_dir: Path) -> None:
    """End-to-end opt → freq → tddft chain on benzene at B3LYP/STO-3G.

    Benzene is small and a closed-shell aromatic; not strictly a TADF
    molecule, but it exercises the entire chain quickly. Asserts that:
      - All four pipeline steps run, finish returns key_results.
      - Optimized energy lands in literature B3LYP/STO-3G range.
      - 30 vibrational modes (3·12 - 6).
      - Thermal corrections are non-null (P0-2 wired).
      - TDDFT yields ≥ 1 singlet and ≥ 1 triplet, ΔE_ST is a real number.
    """
    traj, state = _run_tadf_pipeline("benzene", tmp_runs_dir,
                                     basis="STO-3G", method="B3LYP")

    assert traj.status == "completed", f"trajectory failed: {traj.finish_payload}"
    # Pipeline steps in order
    step_names = [
        s.assistant_message.tool_calls[0].name
        for s in traj.steps if s.assistant_message
        and s.assistant_message.tool_calls
    ]
    assert step_names == [
        "io_lookup_by_name",
        "calc_psi4_optimize",
        "calc_psi4_frequency",
        "calc_psi4_tddft",
        "finish",
    ]

    # Numerical sanity (B3LYP/STO-3G is a very minimal basis; widen range)
    assert state["energy"] is not None
    assert -230.0 < state["energy"] < -228.0, (
        f"benzene B3LYP/STO-3G energy {state['energy']} out of range"
    )
    assert state["freqs"] is not None and len(state["freqs"]) == 30
    assert state["n_imag"] == 0
    # P0-2: thermal corrections must be filled in
    assert state["h_corr"] is not None, "h_corr should be parsed from psi4 log"
    assert state["g_corr"] is not None, "g_corr should be parsed from psi4 log"
    # P0-1: TDDFT delivers excited states
    assert state["s1"] is not None and state["s1"] > 0, "S1 should be > 0 eV"
    assert state["t1"] is not None and state["t1"] > 0, "T1 should be > 0 eV"
    assert state["delta_e_st"] is not None


# ──────────────────────────────────────────────────────────────────────────
# Real TADF anchor (DMAC-BP / 4CzIPN): opt-in only — far too slow for CI
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.skipif(
    not os.environ.get("CHEMASTER_E2E_FULL"),
    reason="DMAC-BP is 82 atoms; opt+freq+tddft takes hours. "
           "Set CHEMASTER_E2E_FULL=1 to run.",
)
def test_tadf_pipeline_dmac_bp(tmp_runs_dir: Path) -> None:
    """Real TADF anchor: DMAC-BP at B3LYP/STO-3G (cheap method, big molecule).

    Even at STO-3G this takes ≥ 1 h on a workstation. Energy / state counts
    are not literature-grade (small basis), but the test proves the agent
    chain holds at scale (82 atoms ~ size of real published TADF emitters).
    """
    t0 = time.time()
    traj, state = _run_tadf_pipeline("DMAC-BP", tmp_runs_dir,
                                     basis="STO-3G", method="B3LYP",
                                     max_turns=12)
    elapsed = time.time() - t0
    print(f"\nDMAC-BP TADF pipeline took {elapsed/60:.1f} min")

    assert traj.status == "completed"
    assert state["energy"] is not None
    assert state["freqs"] is not None and len(state["freqs"]) > 0
    assert state["s1"] is not None
    assert state["t1"] is not None
