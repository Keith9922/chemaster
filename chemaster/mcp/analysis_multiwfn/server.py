"""chem.analysis_multiwfn — MultiWFN wavefunction analysis (subprocess).

MultiWFN (https://sobereva.com/multiwfn/) is the de-facto standard for
post-SCF wavefunction analysis (NTO, NBO, AIM, ELF, Hirshfeld charges,
etc.). Free for academic use; developed by Tian Lu.

This module exposes a single high-level tool `nto_analysis` that runs the
NTO (Natural Transition Orbital) workflow on a TDDFT output (psi4 .molden
or ORCA .gbw). Other analyses (charge populations, orbital localization)
will follow the same input-script subprocess pattern.

Requires:
    - Multiwfn binary on PATH
    - The wavefunction file (.molden / .fch / .gbw) prepared by the QM step
"""

from __future__ import annotations

import logging
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)
mcp = FastMCP("chem.analysis_multiwfn")


def _check_engine() -> tuple[str | None, str | None]:
    """Return (Multiwfn binary path, version) or (None, None)."""
    from chemaster.mcp._common import probe_binary
    path, version = probe_binary(("Multiwfn", "multiwfn"))
    return (path, version) if path else (None, None)


def _run_multiwfn(*, wfn_file: str, command_script: str,
                 workdir: Path, timeout_s: int) -> tuple[int, str, str]:
    """Run Multiwfn with an interactive command script piped on stdin.

    Multiwfn is a menu-driven CLI; you script it by feeding the menu choice
    numbers separated by newlines. The wfn_file is passed as argv[1].
    """
    bin_path, _ = _check_engine()
    if bin_path is None:
        raise FileNotFoundError("Multiwfn")
    proc = subprocess.run(
        [bin_path, wfn_file],
        cwd=workdir,
        input=command_script,
        capture_output=True,
        text=True, timeout=timeout_s,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _parse_nto(stdout: str) -> dict[str, Any]:
    """Parse the NTO occupation table Multiwfn prints for option 18 → 1."""
    pairs: list[dict[str, Any]] = []
    pattern = re.compile(
        r"(\d+)\s+([-+]?\d+\.\d+)\s+(\d+)\s+([-+]?\d+\.\d+)\s+([-+]?\d+\.\d+)",
    )
    for m in pattern.finditer(stdout):
        pairs.append({
            "pair_index": int(m.group(1)),
            "hole_occupation": float(m.group(2)),
            "particle_index": int(m.group(3)),
            "particle_occupation": float(m.group(4)),
            "weight": float(m.group(5)),
        })
    return {"nto_pairs": pairs}


@mcp.tool()
def nto_analysis(
    wavefunction_file: str,
    excited_state: int = 1,
    timeout_s: int = 600,
) -> dict[str, Any]:
    """Natural Transition Orbital analysis (Multiwfn).

    Given a TDDFT output (.molden from psi4 or .gbw/.fch from ORCA), run
    Multiwfn's NTO analysis on the requested excited state. Returns the
    hole/particle occupation pairs and their weights — used in the TADF
    pipeline to characterize CT vs LE excited-state character.

    Args:
        wavefunction_file: absolute path to the .molden / .gbw / .fch file.
        excited_state: which excited state to analyze (1-indexed, default
            S1).
        timeout_s: kill after this many seconds.

    Returns:
        ok=True:
          {ok, result: {nto_pairs: [...]}, warnings, meta}
        ok=False:
          {ok=False, error_code: ENGINE_NOT_FOUND | FILE_NOT_FOUND |
                                 MULTIWFN_RUNTIME_ERROR | TIMEOUT,
           details, suggestion}
    """
    bin_path, version = _check_engine()
    if bin_path is None:
        return {
            "ok": False,
            "error_code": "ENGINE_NOT_FOUND",
            "details": "Multiwfn binary not on PATH.",
            "suggestion": (
                "Download Multiwfn from http://sobereva.com/multiwfn/ "
                "(academic-free). Add the install dir to PATH and ensure "
                "the 'settings.ini' file is readable. ChemMaster uses the "
                "scriptable CLI mode; Multiwfn ≥ 3.7 recommended."
            ),
        }

    wfn_path = Path(wavefunction_file)
    if not wfn_path.is_file():
        return {
            "ok": False,
            "error_code": "FILE_NOT_FOUND",
            "details": f"wavefunction_file does not exist: {wavefunction_file}",
            "suggestion": (
                "Generate the .molden / .gbw / .fch from the prior TDDFT "
                "step. For psi4: psi4.molden(wfn, 'state.molden'). For "
                "ORCA: include `printlevel 5` in input."
            ),
        }

    # Multiwfn menu choices to drive NTO:
    #   18    → Electron excitation analysis
    #    1    → Natural Transition Orbital (NTO) analysis
    #   <state index>
    #    0    → return to main menu
    #    q    → quit
    script = f"18\n1\n{excited_state}\n0\nq\n"

    wall_start = time.time()
    with tempfile.TemporaryDirectory(prefix="multiwfn_nto_") as tmp:
        workdir = Path(tmp)
        try:
            rc, stdout, stderr = _run_multiwfn(
                wfn_file=str(wfn_path), command_script=script,
                workdir=workdir, timeout_s=timeout_s,
            )
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "error_code": "TIMEOUT",
                "details": f"Multiwfn exceeded {timeout_s}s.",
                "suggestion": "Increase timeout_s.",
                "meta": {"version": version,
                         "wall_time_s": round(time.time() - wall_start, 1)},
            }

        if rc != 0:
            return {
                "ok": False,
                "error_code": "MULTIWFN_RUNTIME_ERROR",
                "details": (stderr or stdout)[-1500:],
                "suggestion": (
                    "Multiwfn often complains about basis-function ordering "
                    "in non-Gaussian wavefunction files; convert to .fch "
                    "via formchk first."
                ),
                "meta": {"version": version, "returncode": rc},
            }

        nto = _parse_nto(stdout)

    return {
        "ok": True,
        "result": nto,
        "warnings": (
            ["NTO parser is coarse; verify against Multiwfn's text output."]
            if not nto["nto_pairs"] else []
        ),
        "meta": {
            "version": version,
            "wall_time_s": round(time.time() - wall_start, 1),
            "excited_state": excited_state,
        },
    }


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
