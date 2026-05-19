"""chem.calc_orca — ORCA quantum chemistry wrapper (subprocess).

Drives the ORCA binary (`orca` on PATH) via subprocess. Provides single-point
and geometry-optimization tools that complement psi4 with ORCA-specific
strengths:

- DLPNO-CCSD(T) (gold-standard energetics)
- Range-separated functionals (ωB97X-D / V) tuned for excited states
- Faster RIJCOSX for large systems

Requires ORCA installed and on PATH. ORCA is academic-free but not
open-source; download from https://orcaforum.kofo.mpg.de/ .
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)
mcp = FastMCP("chem.calc_orca")

HARTREE_TO_EV = 27.211386246


# ══════════════════════════════════════════════════════════════════════════════
# Engine probing
# ══════════════════════════════════════════════════════════════════════════════


def _check_engine() -> tuple[str | None, str | None]:
    """Return (orca_path, version_string) or (None, None) if not installed."""
    orca_path = shutil.which("orca")
    if not orca_path:
        return None, None
    try:
        proc = subprocess.run(
            [orca_path], capture_output=True, text=True, timeout=10,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        m = re.search(r"Program Version\s+(\S+)", out)
        version = m.group(1) if m else "unknown"
        return orca_path, version
    except Exception:
        return orca_path, "unknown"


# ══════════════════════════════════════════════════════════════════════════════
# Input file helpers
# ══════════════════════════════════════════════════════════════════════════════


def _xyz_to_orca_geom(xyz: str, charge: int, multiplicity: int) -> str:
    """Convert standard xyz block (atom count + comment + atoms) into the
    ``* xyz <charge> <mult> ... *`` block ORCA expects.
    """
    lines = [ln for ln in xyz.strip().splitlines() if ln.strip()]
    if not lines:
        raise ValueError("empty geometry_xyz")
    try:
        n_atoms = int(lines[0].strip())
        atom_lines = lines[2 : 2 + n_atoms]
    except ValueError:
        atom_lines = lines
    coords = "\n".join(atom_lines)
    return f"* xyz {charge} {multiplicity}\n{coords}\n*\n"


def _build_input(*, keywords: str, geom_block: str, nproc: int,
                memory_gb: int) -> str:
    per_thread_mb = int(memory_gb * 1024 / max(1, nproc))
    return "\n".join([
        f"! {keywords}",
        f"%pal nprocs {nproc} end",
        f"%maxcore {per_thread_mb}",
        "",
        geom_block,
    ])


def _run_orca(*, input_text: str, workdir: Path,
             timeout_s: int) -> tuple[int, str, str]:
    """Run ORCA in workdir. Returns (returncode, stdout, stderr).

    ORCA insists on being invoked with the absolute path to its binary so
    its child processes (orca_scfgrad etc.) can find themselves.
    """
    orca_path, _ = _check_engine()
    if orca_path is None:
        raise FileNotFoundError("orca")
    inp_path = workdir / "calc.inp"
    out_path = workdir / "calc.out"
    inp_path.write_text(input_text, encoding="ascii")
    proc = subprocess.run(
        [orca_path, str(inp_path)],
        cwd=workdir, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, timeout=timeout_s,
    )
    out_path.write_text(proc.stdout or "")
    return proc.returncode, proc.stdout, proc.stderr


# ══════════════════════════════════════════════════════════════════════════════
# Output parsing
# ══════════════════════════════════════════════════════════════════════════════


_FINAL_E_PATTERNS = [
    re.compile(r"FINAL SINGLE POINT ENERGY\s+([-+]?\d+\.\d+)"),
    re.compile(r"Final energy:\s+([-+]?\d+\.\d+)"),
]


def _parse_final_energy(stdout: str) -> float | None:
    for pat in _FINAL_E_PATTERNS:
        last = None
        for m in pat.finditer(stdout):
            last = float(m.group(1))
        if last is not None:
            return last
    return None


def _parse_optimized_xyz(stdout: str, workdir: Path) -> str | None:
    """ORCA writes the final optimized geometry to ``calc.xyz``."""
    xyz_file = workdir / "calc.xyz"
    if xyz_file.exists():
        return xyz_file.read_text()
    blocks = re.findall(
        r"CARTESIAN COORDINATES \(ANGSTROEM\)\s*[-=]+\s*\n(.*?)(?:\n\s*\n|----)",
        stdout, re.DOTALL,
    )
    if not blocks:
        return None
    last = blocks[-1].strip().splitlines()
    coords = []
    for line in last:
        parts = line.split()
        if len(parts) == 4:
            sym, x, y, z = parts
            coords.append(f"{sym} {x} {y} {z}")
    if not coords:
        return None
    return f"{len(coords)}\noptimized geometry\n" + "\n".join(coords) + "\n"


def _detect_scf_failure(stdout: str) -> bool:
    return bool(re.search(
        r"SCF NOT CONVERGED|TROUBLE IN SCF|SCF DID NOT CONVERGE",
        stdout,
    ))


def _detect_geometry_failure(stdout: str) -> bool:
    return bool(re.search(
        r"GEOMETRY OPTIMIZATION FAILED|OPT NOT CONVERGED",
        stdout,
    ))


# ══════════════════════════════════════════════════════════════════════════════
# Tools
# ══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
def single_point(
    geometry_xyz: str,
    charge: int = 0,
    multiplicity: int = 1,
    method: str = "B3LYP D3BJ",
    basis: str = "def2-SVP",
    extra_keywords: str = "",
    n_threads: int = 4,
    memory_gb: int = 4,
    timeout_s: int = 1800,
) -> dict[str, Any]:
    """ORCA single-point energy.

    Use this when you need ORCA-specific functionality (DLPNO-CCSD(T) for
    accurate energetics, ωB97X for charge-transfer excited states) or when
    psi4 is too slow for the system size.

    Args:
        geometry_xyz: Standard xyz block (atom count + comment + atoms).
        charge / multiplicity: as usual.
        method: ORCA functional + dispersion keywords. Examples:
            "B3LYP D3BJ"             — default DFT
            "wB97X-D3BJ"             — range-separated DFT
            "DLPNO-CCSD(T) TightSCF" — gold-standard energetics
            "RI-MP2"                 — fast post-HF
        basis: e.g. "def2-SVP" / "def2-TZVP" / "cc-pVTZ" / "ma-def2-TZVP".
        extra_keywords: appended to the ORCA `!` line. Common: "TightSCF
            RIJCOSX def2/J" for fast hybrid DFT on big systems.
        n_threads: ORCA `%pal nprocs`.
        memory_gb: total memory budget; per-thread `%maxcore` is derived.
        timeout_s: kill the subprocess after this many seconds.

    Returns:
        ok=True:
          {ok, result: {energy: {value, unit}, method, basis}, warnings, meta}
        ok=False:
          {ok=False, error_code: ENGINE_NOT_FOUND | SCF_NOT_CONVERGED |
                                 TIMEOUT | ORCA_RUNTIME_ERROR,
           details, suggestion}
    """
    orca_path, version = _check_engine()
    if not orca_path:
        return {
            "ok": False,
            "error_code": "ENGINE_NOT_FOUND",
            "details": "orca binary not on PATH.",
            "suggestion": (
                "Download ORCA from https://orcaforum.kofo.mpg.de/ "
                "(academic-free), extract, and add the install dir to PATH. "
                "Pin a single MPI provider (OpenMPI 4.x for ORCA 5.x)."
            ),
        }

    keywords = f"{method} {basis} {extra_keywords}".strip()
    geom = _xyz_to_orca_geom(geometry_xyz, charge, multiplicity)
    inp = _build_input(keywords=keywords, geom_block=geom,
                       nproc=n_threads, memory_gb=memory_gb)

    wall_start = time.time()
    with tempfile.TemporaryDirectory(prefix="orca_sp_") as tmp:
        workdir = Path(tmp)
        try:
            rc, stdout, stderr = _run_orca(
                input_text=inp, workdir=workdir, timeout_s=timeout_s,
            )
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "error_code": "TIMEOUT",
                "details": f"ORCA exceeded {timeout_s}s.",
                "suggestion": "Increase timeout_s, or pre-screen with xTB.",
                "meta": {"orca_version": version,
                         "wall_time_s": round(time.time() - wall_start, 1)},
            }

        if _detect_scf_failure(stdout):
            return {
                "ok": False,
                "error_code": "SCF_NOT_CONVERGED",
                "details": "ORCA SCF did not converge.",
                "suggestion": (
                    "Add 'SlowConv' or 'VerySlowConv' to extra_keywords; "
                    "try a smaller basis first, or use 'AutoStart' with a "
                    "previous wavefunction."
                ),
                "meta": {"orca_version": version, "returncode": rc,
                         "wall_time_s": round(time.time() - wall_start, 1)},
            }

        energy = _parse_final_energy(stdout)
        if energy is None or rc != 0:
            return {
                "ok": False,
                "error_code": "ORCA_RUNTIME_ERROR",
                "details": (stderr or stdout)[-1000:],
                "suggestion": (
                    "Check the input keywords; ORCA is picky about syntax. "
                    "Inspect calc.out for the full traceback."
                ),
                "meta": {"orca_version": version, "returncode": rc,
                         "wall_time_s": round(time.time() - wall_start, 1)},
            }

    return {
        "ok": True,
        "result": {
            "energy": {"value": energy, "unit": "Hartree"},
            "method": method,
            "basis": basis,
        },
        "warnings": [],
        "meta": {
            "orca_version": version,
            "wall_time_s": round(time.time() - wall_start, 1),
            "keywords": keywords,
        },
    }


@mcp.tool()
def optimize(
    geometry_xyz: str,
    charge: int = 0,
    multiplicity: int = 1,
    method: str = "B3LYP D3BJ",
    basis: str = "def2-SVP",
    extra_keywords: str = "TightSCF",
    n_threads: int = 4,
    memory_gb: int = 4,
    timeout_s: int = 7200,
) -> dict[str, Any]:
    """ORCA geometry optimization.

    Same signature as ``single_point`` but appends ``Opt`` to the keyword
    line. ORCA's optimizer (`OPT`) is more robust than psi4's optking on
    awkward geometries (large rings, transition-metal complexes).

    Always follow with a frequency calculation to confirm the geometry is a
    true minimum. Frequency analysis lives in calc_psi4 (ORCA's
    NumFreq/AnFreq pathway is not yet wired here).

    Returns the optimized xyz, final energy, and a converged flag.
    """
    orca_path, version = _check_engine()
    if not orca_path:
        return {
            "ok": False,
            "error_code": "ENGINE_NOT_FOUND",
            "details": "orca binary not on PATH.",
            "suggestion": (
                "Download ORCA from https://orcaforum.kofo.mpg.de/ "
                "(academic-free) and add it to PATH."
            ),
        }

    keywords = f"{method} {basis} Opt {extra_keywords}".strip()
    geom = _xyz_to_orca_geom(geometry_xyz, charge, multiplicity)
    inp = _build_input(keywords=keywords, geom_block=geom,
                       nproc=n_threads, memory_gb=memory_gb)

    wall_start = time.time()
    with tempfile.TemporaryDirectory(prefix="orca_opt_") as tmp:
        workdir = Path(tmp)
        try:
            rc, stdout, stderr = _run_orca(
                input_text=inp, workdir=workdir, timeout_s=timeout_s,
            )
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "error_code": "TIMEOUT",
                "details": f"ORCA opt exceeded {timeout_s}s.",
                "suggestion": "Pre-optimize with xTB; or use 'LooseOpt'.",
                "meta": {"orca_version": version,
                         "wall_time_s": round(time.time() - wall_start, 1)},
            }

        if _detect_scf_failure(stdout):
            return {
                "ok": False,
                "error_code": "SCF_NOT_CONVERGED",
                "details": "SCF failure during optimization.",
                "suggestion": "Add 'SlowConv'; reduce basis temporarily.",
                "meta": {"orca_version": version, "returncode": rc},
            }

        if _detect_geometry_failure(stdout):
            return {
                "ok": False,
                "error_code": "GEOMETRY_NOT_CONVERGED",
                "details": "ORCA opt did not converge.",
                "suggestion": (
                    "Try 'LooseOpt' or increase 'maxiter' inside %geom; "
                    "low-frequency torsions can trap the optimizer."
                ),
                "meta": {"orca_version": version},
            }

        energy = _parse_final_energy(stdout)
        opt_xyz = _parse_optimized_xyz(stdout, workdir)
        if energy is None or opt_xyz is None or rc != 0:
            return {
                "ok": False,
                "error_code": "ORCA_RUNTIME_ERROR",
                "details": (stderr or stdout)[-1000:],
                "suggestion": "Inspect calc.out for the full traceback.",
                "meta": {"orca_version": version, "returncode": rc},
            }

    return {
        "ok": True,
        "result": {
            "optimized_geometry_xyz": opt_xyz,
            "final_energy": {"value": energy, "unit": "Hartree"},
            "converged": True,
            "method": method,
            "basis": basis,
        },
        "warnings": [],
        "meta": {
            "orca_version": version,
            "wall_time_s": round(time.time() - wall_start, 1),
            "keywords": keywords,
        },
    }


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
