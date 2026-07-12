"""chem.calc_bdf — BDF wrapper (subprocess).

BDF (Beijing Density Functional, https://bdf-manual.readthedocs.io) is the
TADF pipeline's go-to tool for spin-orbit coupling (X2C-TDA / RPA). It's
academic-free, developed by Wenjian Liu's group at Peking University.

This module wires the SOC matrix-element calculation. Ground-state SCF and
TDDFT can also be done in BDF, but for ChemMaster we prefer psi4 / ORCA for
those steps and use BDF specifically for SOC, where it has unique strengths
(full Breit-Pauli + state-interaction).

Requires:
    - BDF binary on PATH (`bdf` or `bdfdrv.py`)
    - BDFHOME environment variable
    - Valid license file at $BDFHOME/license.dat (academic-free)
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)
mcp = FastMCP("chem.calc_bdf")


def _check_engine() -> tuple[str | None, str | None, str | None]:
    """Return (binary_path, version, BDFHOME) or (None, None, None)."""
    from chemaster.mcp._common import probe_binary
    path, version = probe_binary(
        ("bdfdrv.py", "bdf"), version_args=["--version"],
        version_regex=r"BDF\s+(?:Version\s+)?(\S+)",
    )
    if not path:
        return None, None, None
    return path, version, os.environ.get("BDFHOME")


def _xyz_to_bdf_geom(xyz: str, charge: int, multiplicity: int) -> str:
    """Convert standard xyz block into BDF '$compass / Geometry' input."""
    lines = [ln for ln in xyz.strip().splitlines() if ln.strip()]
    try:
        n_atoms = int(lines[0].strip())
        atom_lines = lines[2 : 2 + n_atoms]
    except ValueError:
        atom_lines = lines
    coords = "\n".join(atom_lines)
    return (
        "$compass\n"
        "Geometry\n"
        f"{coords}\n"
        "End geometry\n"
        f"Charge\n{charge}\n"
        f"Spin\n{multiplicity - 1}\n"          # BDF uses 2S, not 2S+1
        "Basis\n  def2-svp\n"
        "skeleton\n"
        "$end\n"
    )


def _parse_soc(out_text: str) -> dict[str, Any]:
    """Parse BDF SOC output for matrix elements between S1 and T1.

    BDF prints a SOC matrix block; this is a coarse parser meant to keep
    the MCP working surface alive until a full-fidelity wrapper is added.
    """
    matches = re.findall(
        r"SOC.*?(\d+)\s*-\s*(\d+).*?([-+]?\d+\.\d+)\s*cm-1",
        out_text,
    )
    soc_elements = []
    for s, t, val in matches:
        soc_elements.append({
            "state_i": int(s),
            "state_j": int(t),
            "matrix_element": {"value": float(val), "unit": "cm^-1"},
        })
    return {"soc_elements": soc_elements}


@mcp.tool()
def soc(
    geometry_xyz: str,
    charge: int = 0,
    multiplicity: int = 1,
    method: str = "B3LYP",
    n_singlets: int = 4,
    n_triplets: int = 4,
    timeout_s: int = 7200,
) -> dict[str, Any]:
    """Spin-orbit coupling matrix elements (BDF X2C-TDA).

    THE step in the TADF pipeline that's hard to get right elsewhere. BDF's
    X2C-TDA produces full Breit-Pauli SOC integrals; psi4 doesn't have this
    natively, and ORCA's RI-SOMF is faster but less accurate.

    Args:
        geometry_xyz: ground-state optimized geometry.
        charge / multiplicity: ground-state.
        method: DFT functional for the underlying TDDFT (default B3LYP).
        n_singlets, n_triplets: how many states to include in the SOC
            matrix.
        timeout_s: kill after this many seconds.

    Returns:
        ok=True:
          {ok, result: {soc_elements: [{state_i, state_j, matrix_element}]},
           warnings, meta}
        ok=False:
          {ok=False, error_code: ENGINE_NOT_FOUND | NO_BDFHOME |
                                 BDF_RUNTIME_ERROR | TIMEOUT,
           details, suggestion}
    """
    bdf_path, version, bdfhome = _check_engine()
    if bdf_path is None:
        return {
            "ok": False,
            "error_code": "ENGINE_NOT_FOUND",
            "details": "Neither 'bdf' nor 'bdfdrv.py' found on PATH.",
            "suggestion": (
                "Download BDF from https://bdf-manual.readthedocs.io "
                "(academic-free). Set BDFHOME and add $BDFHOME/sbin to PATH. "
                "BDF is the recommended SOC engine for the ChemMaster TADF "
                "pipeline."
            ),
        }
    if not bdfhome:
        return {
            "ok": False,
            "error_code": "NO_BDFHOME",
            "details": "BDFHOME environment variable is not set.",
            "suggestion": "Export BDFHOME=/path/to/bdf and re-run.",
        }

    geom = _xyz_to_bdf_geom(geometry_xyz, charge, multiplicity)
    inp = (
        geom
        + "\n$xuanyuan\nheff\n  3\nrelaxation\n  1\nsoint\n$end\n"
        + f"\n$scf\n{method}\n$end\n"
        + (f"\n$tdsp\n  itda 1\n  itest 1\n  isf 0\n  iroot {n_singlets}\n$end\n"
           if n_singlets > 0 else "")
        + (f"\n$tdsp\n  itda 1\n  itest 1\n  isf 1\n  iroot {n_triplets}\n$end\n"
           if n_triplets > 0 else "")
    )

    wall_start = time.time()
    with tempfile.TemporaryDirectory(prefix="bdf_soc_") as tmp:
        workdir = Path(tmp)
        inp_path = workdir / "calc.inp"
        inp_path.write_text(inp, encoding="ascii")
        try:
            proc = subprocess.run(
                [bdf_path, str(inp_path)],
                cwd=workdir,
                capture_output=True,
                text=True, timeout=timeout_s,
            )
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "error_code": "TIMEOUT",
                "details": f"BDF exceeded {timeout_s}s.",
                "suggestion": "Increase timeout_s; reduce n_singlets/n_triplets.",
                "meta": {"bdf_version": version,
                         "wall_time_s": round(time.time() - wall_start, 1)},
            }
        if proc.returncode != 0:
            return {
                "ok": False,
                "error_code": "BDF_RUNTIME_ERROR",
                "details": (proc.stderr or proc.stdout)[-1500:],
                "suggestion": (
                    "Inspect the calc.out file in the workdir; BDF prints a "
                    "verbose error trail. Common: license file missing or "
                    "expired, basis-set name typo, geometry too close to "
                    "linearity."
                ),
                "meta": {"bdf_version": version, "returncode": proc.returncode},
            }
        soc_data = _parse_soc(proc.stdout or "")

    return {
        "ok": True,
        "result": soc_data,
        "warnings": [
            "BDF SOC parser is coarse; verify against the raw output."
        ] if not soc_data["soc_elements"] else [],
        "meta": {
            "bdf_version": version, "bdfhome": bdfhome,
            "wall_time_s": round(time.time() - wall_start, 1),
        },
    }


# ══════════════════════════════════════════════════════════════════════════════
# v3.0: ground-state opt + TDDFT in BDF (in addition to soc).
#
# These complete the BDF wrapper so ChemMaster can use BDF as a standalone
# backend for the entire excited-state pipeline, not just the SOC step.
# ══════════════════════════════════════════════════════════════════════════════


def _bdf_input_for_opt(geom: str, method: str, basis: str) -> str:
    return (
        geom.replace("def2-svp", basis)  # respect user-specified basis
        + f"\n$scf\n{method}\n$end\n"
        + "\n$compass\nGeometry Optimization\nEnd geometry\n$end\n"
        + "\n$bdfopt\nimethod\n  1\n$end\n"
    )


def _bdf_input_for_tddft(
    geom: str, method: str, basis: str, n_states: int, spin_flip: int,
) -> str:
    sf = 1 if spin_flip else 0
    return (
        geom.replace("def2-svp", basis)
        + f"\n$scf\n{method}\n$end\n"
        + f"\n$tdsp\n  itda 1\n  itest 1\n  isf {sf}\n  iroot {n_states}\n$end\n"
    )


def _parse_scf_energy(stdout: str) -> float | None:
    matches = re.findall(r"E\(SCF\)\s*=\s*(-?\d+\.\d+)", stdout)
    if not matches:
        matches = re.findall(r"Total energy\s*=\s*(-?\d+\.\d+)", stdout)
    if matches:
        return float(matches[-1])
    return None


def _parse_excited_energies(stdout: str) -> list[dict[str, Any]]:
    """Extract TDDFT excited state energies + oscillator strengths."""
    states = []
    pattern = re.compile(
        r"State\s*=\s*(\d+)\s+.*?E\s*=\s*(-?\d+\.\d+)\s*eV.*?f\s*=\s*(\d+\.\d+)",
        re.IGNORECASE,
    )
    for m in pattern.finditer(stdout):
        states.append({
            "state": int(m.group(1)),
            "energy_eV": float(m.group(2)),
            "oscillator_strength": float(m.group(3)),
        })
    return states


@mcp.tool()
def optimize(
    geometry_xyz: str,
    method: str = "B3LYP",
    basis: str = "def2-SVP",
    charge: int = 0,
    multiplicity: int = 1,
    timeout_s: int = 7200,
) -> dict[str, Any]:
    """Ground-state geometry optimization in BDF.

    Returns:
        ok=True: {ok, result: {final_energy, optimized_xyz, converged}, ...}
        ok=False: ENGINE_NOT_FOUND | TIMEOUT | BDF_RUNTIME_ERROR
    """
    bdf_path, version, bdfhome = _check_engine()
    if bdf_path is None:
        return {
            "ok": False, "error_code": "ENGINE_NOT_FOUND",
            "details": "BDF not on PATH",
            "suggestion": "Install BDF and set BDFHOME.",
        }
    if not bdfhome:
        return {"ok": False, "error_code": "NO_BDFHOME",
                "details": "BDFHOME not set",
                "suggestion": "export BDFHOME=<BDF install root> (the "
                              "bdfdrv.py launcher requires it); see the BDF "
                              "install guide."}

    geom = _xyz_to_bdf_geom(geometry_xyz, charge, multiplicity)
    inp = _bdf_input_for_opt(geom, method, basis)

    wall_start = time.time()
    with tempfile.TemporaryDirectory(prefix="bdf_opt_") as tmp:
        workdir = Path(tmp)
        inp_path = workdir / "calc.inp"
        inp_path.write_text(inp, encoding="ascii")
        try:
            proc = subprocess.run(
                [bdf_path, str(inp_path)],
                cwd=workdir, capture_output=True,
                text=True, timeout=timeout_s,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "error_code": "TIMEOUT",
                    "details": f"BDF opt exceeded {timeout_s}s",
                    "suggestion": "Increase timeout_s or start from a "
                                  "pre-optimized (e.g. xTB) geometry.",
                    "meta": {"bdf_version": version}}
        if proc.returncode != 0:
            return {"ok": False, "error_code": "BDF_RUNTIME_ERROR",
                    "details": (proc.stderr or proc.stdout)[-1500:],
                    "suggestion": "Inspect the BDF output tail; try "
                                  "dry_run=True to validate the generated "
                                  "input against the BDF manual first.",
                    "meta": {"bdf_version": version}}
        stdout = proc.stdout or ""
        energy = _parse_scf_energy(stdout)
        converged = "Geometry optimization converged" in stdout or \
                     "Optimization completed" in stdout

    return {
        "ok": True,
        "result": {
            "final_energy": {"value": energy, "unit": "Hartree"},
            "converged": converged,
            "method": method, "basis": basis,
        },
        "warnings": [] if converged else [{"code": "OPT_NOT_CONVERGED",
                                            "message": "BDF opt did not converge"}],
        "meta": {"bdf_version": version,
                 "wall_time_s": round(time.time() - wall_start, 1)},
    }


@mcp.tool()
def tddft(
    geometry_xyz: str,
    method: str = "B3LYP",
    basis: str = "def2-SVP",
    charge: int = 0,
    multiplicity: int = 1,
    n_states: int = 5,
    spin_flip: bool = False,
    timeout_s: int = 7200,
) -> dict[str, Any]:
    """TDDFT vertical excitation in BDF.

    Args:
        spin_flip: True for triplet states from a singlet reference.
    """
    bdf_path, version, bdfhome = _check_engine()
    if bdf_path is None:
        return {"ok": False, "error_code": "ENGINE_NOT_FOUND",
                "details": "BDF not on PATH",
                "suggestion": "Install BDF and set BDFHOME; for SOC-class "
                              "tasks calc_pyscf_x2c_soc is the open-source "
                              "fallback."}
    if not bdfhome:
        return {"ok": False, "error_code": "NO_BDFHOME",
                "details": "BDFHOME not set",
                "suggestion": "export BDFHOME=<BDF install root> (the "
                              "bdfdrv.py launcher requires it); see the BDF "
                              "install guide."}

    geom = _xyz_to_bdf_geom(geometry_xyz, charge, multiplicity)
    inp = _bdf_input_for_tddft(geom, method, basis, n_states, int(spin_flip))

    wall_start = time.time()
    with tempfile.TemporaryDirectory(prefix="bdf_tddft_") as tmp:
        workdir = Path(tmp)
        inp_path = workdir / "calc.inp"
        inp_path.write_text(inp, encoding="ascii")
        try:
            proc = subprocess.run(
                [bdf_path, str(inp_path)],
                cwd=workdir, capture_output=True,
                text=True, timeout=timeout_s,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "error_code": "TIMEOUT",
                    "details": f"BDF TDDFT exceeded {timeout_s}s",
                    "suggestion": "Increase timeout_s, request fewer "
                                  "n_states, or use a smaller basis."}
        if proc.returncode != 0:
            return {"ok": False, "error_code": "BDF_RUNTIME_ERROR",
                    "details": (proc.stderr or proc.stdout)[-1500:],
                    "suggestion": "Inspect the BDF output tail; verify the "
                                  "$tddft block (istore/nroot) matches your "
                                  "BDF version's manual."}
        states = _parse_excited_energies(proc.stdout or "")

    return {
        "ok": True,
        "result": {
            "excited_states": states,
            "n_states": len(states),
            "spin_flip": bool(spin_flip),
            "method": method, "basis": basis,
        },
        "warnings": [],
        "meta": {"bdf_version": version,
                 "wall_time_s": round(time.time() - wall_start, 1)},
    }


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
