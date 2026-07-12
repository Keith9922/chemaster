"""chem.calc_pyscf — PySCF X2C SOC MCP server.

The open-source reference implementation for the BDF wrapper in this work.
PySCF >=2.13 ships an exact-2-component (X2C) one-electron relativistic
Hamiltonian that, applied to a generalised Kohn-Sham (GKS) reference,
yields a two-component calculation including spin-orbit coupling — the
same physics BDF computes via X2C-TDA, in an open-source, pip-installable
package that runs on macOS arm64 natively.

Tools:
    single_point         — non-relativistic / scalar-relativistic / SOC SCF
    x2c_soc              — focused: scalar-relativistic + SOC pair, with
                           reported scalar and SOC corrections in meV

Errors:
    ENGINE_NOT_FOUND     — pyscf not importable
    SCF_NOT_CONVERGED    — kernel returned converged=False
    INVALID_GEOMETRY     — XYZ string couldn't be parsed
"""

from __future__ import annotations

import logging
import time
from typing import Any

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)
mcp = FastMCP("chem.calc_pyscf")

HARTREE_TO_EV = 27.211386246
HARTREE_TO_MEV = 27211.386246


def _check_engine() -> tuple[str | None, str | None]:
    """Returns (version, None) on success, (None, error_message) on failure."""
    try:
        import pyscf
        return pyscf.__version__, None
    except ImportError as exc:
        return None, f"pyscf not installed: {exc}. Try: pip install pyscf"


def _xyz_to_pyscf_atom(xyz: str) -> str:
    """Convert standard XYZ string to PySCF 'C 0 0 0; H 0 0 1' format."""
    lines = [ln for ln in xyz.strip().splitlines() if ln.strip()]
    if not lines:
        raise ValueError("Empty XYZ")
    # Skip atom-count + comment lines if present
    first = lines[0].strip().split()
    if len(first) == 1 and first[0].isdigit():
        n_atoms = int(first[0])
        atom_lines = lines[2:2 + n_atoms] if len(lines) > 2 else []
    else:
        atom_lines = lines
    if not atom_lines:
        raise ValueError("No atom lines found in XYZ")
    return "; ".join(ln.strip() for ln in atom_lines)


@mcp.tool()
def single_point(
    geometry_xyz: str,
    method: str = "B3LYP",
    basis: str = "def2-svp",
    charge: int = 0,
    multiplicity: int = 1,
    relativistic: str = "none",
    max_cycle: int = 100,
) -> dict[str, Any]:
    """Compute SCF single-point energy with PySCF.

    Args:
        geometry_xyz:  XYZ geometry (with or without atom-count header).
        method:        Functional (e.g. 'B3LYP', 'PBE0', 'wB97X-D') or 'HF'.
        basis:         Basis set label (e.g. 'sto-3g', '6-31g(d)', 'def2-svp').
        charge:        Net charge.
        multiplicity:  Spin multiplicity (1 = singlet, 3 = triplet, ...).
        relativistic:  'none' | 'scalar' (X2C-1e via .x2c() decorator) |
                       'soc'  (two-component GKS+X2C-1e, includes SOC).
        max_cycle:     SCF iteration cap.

    Returns:
        dict with: ok, energy_hartree, converged, n_basis, n_electrons,
                   wall_time_s, method, basis, relativistic, warnings.
        Or on failure: ok=False, error_code in
                       {ENGINE_NOT_FOUND, INVALID_GEOMETRY, SCF_NOT_CONVERGED},
                       suggestion.
    """
    version, err = _check_engine()
    if err:
        return {
            "ok": False,
            "error_code": "ENGINE_NOT_FOUND",
            "details": err,
            "suggestion": (
                "Install PySCF: pip install pyscf  "
                "(open-source, MIT-licensed, Linux/macOS/Windows-WSL)."
            ),
        }

    try:
        atom_str = _xyz_to_pyscf_atom(geometry_xyz)
    except Exception as exc:
        return {
            "ok": False,
            "error_code": "INVALID_GEOMETRY",
            "details": f"Failed to parse XYZ: {exc}",
            "suggestion": "Ensure XYZ has either 'N\\ncomment\\nElement x y z' "
                          "header or a flat 'Element x y z' list.",
        }

    if relativistic not in ("none", "scalar", "soc"):
        return {
            "ok": False,
            "error_code": "INVALID_OPTION",
            "details": f"relativistic={relativistic!r} not in "
                       "('none', 'scalar', 'soc')",
        }

    from pyscf import dft, gto, scf

    spin = multiplicity - 1
    mol = gto.M(
        atom=atom_str,
        basis=basis,
        charge=charge,
        spin=spin,
        verbose=0,
        symmetry=False,
    )

    method_norm = method.upper()
    is_dft = method_norm not in ("HF", "RHF", "UHF", "ROHF")

    t0 = time.time()
    if relativistic == "soc":
        # Two-component generalised reference + X2C-1e
        if is_dft:
            mf = mol.GKS(xc=method).x2c1e()
        else:
            mf = mol.GHF().x2c1e()
    elif relativistic == "scalar":
        # Scalar relativistic via decorator (sfx2c1e under the hood).
        if is_dft:
            base = dft.UKS(mol, xc=method) if spin > 0 else dft.RKS(mol, xc=method)
        else:
            base = scf.UHF(mol) if spin > 0 else scf.RHF(mol)
        mf = base.x2c()
    else:
        if is_dft:
            mf = dft.UKS(mol, xc=method) if spin > 0 else dft.RKS(mol, xc=method)
        else:
            mf = scf.UHF(mol) if spin > 0 else scf.RHF(mol)

    mf.max_cycle = max_cycle
    energy = mf.kernel()
    wall = time.time() - t0
    converged = bool(mf.converged)

    if not converged:
        # 与其余 server 的契约一致：失败 → ok=False（此前 ok=True 与
        # error_code 并存，agent 侧按 ok 判读会把不收敛当成功；x2c_soc
        # 也会拿不收敛的能量继续算修正值）。
        return {
            "ok": False,
            "error_code": "SCF_NOT_CONVERGED",
            "details": f"SCF did not converge in {max_cycle} cycles.",
            "suggestion": (
                "Increase max_cycle, switch the initial guess, or start "
                "from a smaller-basis converged density."
            ),
            "data_source": "real_pyscf",
            "engine": f"pyscf {version}",
            "method": method,
            "basis": basis,
            "relativistic": relativistic,
            "charge": charge,
            "multiplicity": multiplicity,
            "energy_hartree_unconverged": float(energy),
            "converged": False,
            "wall_time_s": round(wall, 3),
        }

    return {
        "ok": True,
        "data_source": "real_pyscf",
        "engine": f"pyscf {version}",
        "method": method,
        "basis": basis,
        "relativistic": relativistic,
        "charge": charge,
        "multiplicity": multiplicity,
        "energy_hartree": float(energy),
        "energy_eV": float(energy) * HARTREE_TO_EV,
        "converged": True,
        "n_basis": int(mol.nao_nr()),
        "n_electrons": int(mol.nelectron),
        "wall_time_s": round(wall, 3),
        "warnings": [],
    }


@mcp.tool()
def x2c_soc(
    geometry_xyz: str,
    method: str = "B3LYP",
    basis: str = "def2-svp",
    charge: int = 0,
    multiplicity: int = 1,
    max_cycle: int = 100,
) -> dict[str, Any]:
    """Three-stage X2C analysis: NR + scalar + SOC, with corrections in meV.

    Open-source reference for the BDF X2C-TDA SOC pathway. Runs three
    SCF calculations (non-rel, scalar X2C, two-component X2C+SOC) on the
    same geometry/method/basis and reports the scalar relativistic
    correction and the SOC correction.

    Use case in this work: anthracene C/H system → SOC correction is
    sub-meV (chemically expected for first-row elements). For heavy
    elements (Fe, Pt, Ir, Br, I, ...) SOC corrections become much larger.

    Returns the three energies + corrections + interpretation hint.
    """
    version, err = _check_engine()
    if err:
        return {
            "ok": False,
            "error_code": "ENGINE_NOT_FOUND",
            "details": err,
            "suggestion": "pip install pyscf",
        }

    common = {"geometry_xyz": geometry_xyz, "method": method, "basis": basis,
              "charge": charge, "multiplicity": multiplicity, "max_cycle": max_cycle}
    nr = single_point(relativistic="none", **common)
    if not nr.get("ok"):
        return {**nr, "stage_failed": "nr"}
    sc = single_point(relativistic="scalar", **common)
    if not sc.get("ok"):
        return {**sc, "stage_failed": "scalar"}
    soc = single_point(relativistic="soc", **common)
    if not soc.get("ok"):
        return {**soc, "stage_failed": "soc"}

    e_nr = nr["energy_hartree"]
    e_sc = sc["energy_hartree"]
    e_soc = soc["energy_hartree"]
    return {
        "ok": True,
        "data_source": "real_pyscf",
        "engine": f"pyscf {version}",
        "method": method,
        "basis": basis,
        "stages": {
            "nr": {"energy_hartree": e_nr, "wall_time_s": nr["wall_time_s"]},
            "scalar": {"energy_hartree": e_sc, "wall_time_s": sc["wall_time_s"]},
            "soc": {"energy_hartree": e_soc, "wall_time_s": soc["wall_time_s"]},
        },
        "scalar_correction_meV": round((e_sc - e_nr) * HARTREE_TO_MEV, 4),
        "soc_correction_meV": round((e_soc - e_sc) * HARTREE_TO_MEV, 4),
        "total_wall_time_s": round(
            nr["wall_time_s"] + sc["wall_time_s"] + soc["wall_time_s"], 3),
        "interpretation": (
            "scalar_correction_meV is the picture-change scalar relativistic "
            "shift; soc_correction_meV is the residual two-component (SOC) "
            "contribution. For C/H molecules SOC ≪ 1 meV is expected; for "
            "heavy elements (Fe/Pt/Ir/Br/I) the SOC term grows to tens-to-"
            "hundreds of meV."
        ),
    }


def main() -> None:
    """Run as standalone MCP server over stdio."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
