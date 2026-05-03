"""Integration test for optimize_excited_state — real psi4, real H2O S1 opt.

Cheap smoke test (~10 s on 2 cores) that proves:
1. The MCP wrapper passes the right TDA + follow_root options to psi4.
2. psi4's TD-DFT optimizer actually converges.
3. The returned optimized geometry has a longer O-H bond than the GS
   geometry (a known physics check: H2O S1 is dissociative along O-H).
4. The excitation energy at the optimized geometry is parseable.

Heavier benchmarks (formaldehyde S1 with bigger basis) are gated behind
CHEMASTER_E2E_FULL=1.
"""

from __future__ import annotations

import math
import os

import pytest

from chemaster.mcp.calc_psi4.server import optimize_excited_state


# ─── small smoke test: H2O S1 / B3LYP / sto-3g ────────────────────────
H2O_GS_XYZ = """3
H2O ground state geometry
O  0.000000  -0.000000   0.117379
H  0.000000   0.757063  -0.469516
H  0.000000  -0.757063  -0.469516"""


def _bond_length(xyz: str, i: int, j: int) -> float:
    """Atom-i to atom-j bond length (Å) from a psi4 save_string_xyz block.

    psi4's save_string_xyz produces a block where the first line is
    "charge multiplicity" and subsequent lines are "Element x y z".
    """
    rows = [r.split() for r in xyz.strip().splitlines() if r.strip()]
    # First row is "charge multiplicity"; coordinate rows have 4 tokens.
    coord_rows = [r for r in rows if len(r) == 4]
    xi, yi, zi = (float(coord_rows[i][k]) for k in (1, 2, 3))
    xj, yj, zj = (float(coord_rows[j][k]) for k in (1, 2, 3))
    return math.sqrt((xi - xj) ** 2 + (yi - yj) ** 2 + (zi - zj) ** 2)


@pytest.mark.integration
def test_h2o_s1_opt_smoke() -> None:
    """H2O S1 opt at B3LYP/sto-3g converges in ~10s and elongates O-H bonds."""
    result = optimize_excited_state(
        H2O_GS_XYZ,
        target_state=1,
        target_spin="singlet",
        method="B3LYP",
        basis="sto-3g",
        n_states=3,
        convergence="loose",
        n_threads=2,
        memory_gb=2,
    )
    assert result["ok"], result.get("details") or result
    res = result["result"]
    assert res["converged"] is True
    assert res["target_state"] == 1
    assert res["target_spin"] == "singlet"
    assert res["tda"] is True

    # Sanity on numbers (B3LYP/sto-3g is small but stable on H2O S1):
    # GS energy is ~-75.31 Ha; S1-relaxed E_total should be slightly higher
    # (less negative) than the S1 *vertical* on the GS geometry but still
    # bound. We just check it's in the H2O ballpark.
    e_total = res["final_total_energy"]["value"]
    assert -76.5 < e_total < -75.0, f"E_total out of H2O ballpark: {e_total}"

    # Excitation energy at the optimized geometry: must be parseable and
    # within a sane DFT range (5-15 eV for H2O S1 at sto-3g).
    e_exc = res["excitation_energy_at_opt"]
    assert e_exc is not None, "excitation energy not parsed from log"
    assert 4.0 < e_exc["value"] < 15.0, f"unphysical S1 energy: {e_exc}"

    # Physics check: S1 H2O is dissociative along the O-H stretch, so the
    # optimized O-H bond should be longer than the GS 0.957 Å.
    opt_xyz = res["optimized_geometry_xyz"]
    rOH_1 = _bond_length(opt_xyz, 0, 1)
    rOH_2 = _bond_length(opt_xyz, 0, 2)
    assert rOH_1 > 0.96, f"S1 O-H1 not elongated: {rOH_1:.4f} Å"
    assert rOH_2 > 0.96, f"S1 O-H2 not elongated: {rOH_2:.4f} Å"


@pytest.mark.integration
def test_invalid_target_state_real_psi4() -> None:
    """Asking for a root higher than n_states triggers the validation
    short-circuit BEFORE we hit psi4 (so this is fast and free)."""
    result = optimize_excited_state(
        H2O_GS_XYZ, target_state=5, n_states=3,
    )
    assert result["ok"] is False
    assert result["error_code"] == "INVALID_TARGET_STATE"


@pytest.mark.integration
@pytest.mark.skipif(
    not os.environ.get("CHEMASTER_E2E_FULL"),
    reason="formaldehyde S1 opt at def2-SVP takes ~3 min; "
           "set CHEMASTER_E2E_FULL=1 to run.",
)
def test_formaldehyde_s1_opt_full() -> None:
    """HCHO S1 (n→π*) opt at B3LYP/def2-SVP — real-paper small-molecule case.

    Reference: HCHO S1 vertical is ~3.8 eV at TDA-B3LYP/def2-SVP; adiabatic
    is ~3.3 eV. The S1 minimum is pyramidalized (out-of-plane H wagging).
    """
    hcho_xyz = """4
HCHO planar GS
C  0.000  0.000   0.000
O  0.000  0.000   1.220
H  0.940  0.000  -0.560
H -0.940  0.000  -0.560"""
    result = optimize_excited_state(
        hcho_xyz,
        target_state=1,
        target_spin="singlet",
        method="B3LYP",
        basis="def2-SVP",
        n_states=4,
        convergence="normal",
        n_threads=4,
        memory_gb=4,
    )
    assert result["ok"], result
    res = result["result"]
    assert res["converged"]
    e_exc = res["excitation_energy_at_opt"]["value"]
    # Adiabatic S1 of HCHO at TDA-B3LYP/def2-SVP is ~2.8-3.5 eV
    assert 2.0 < e_exc < 4.5, f"HCHO S1 adiabatic out of range: {e_exc} eV"
