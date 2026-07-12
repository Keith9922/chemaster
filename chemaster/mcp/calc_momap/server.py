"""chem.calc_momap — MOMAP wrapper (subprocess).

MOMAP (Molecular Materials Property Prediction Package, https://momap.chem-i.com)
is the photophysics rate / spectrum / dynamics engine developed by Shuai's group
at Tsinghua. It is the gold standard for vibrationally resolved emission
spectra (Strickler-Berg + Duschinsky + thermal vibration correlation function),
TVCF rate constants for k_r / k_nr / k_isc / k_risc, and surface-hopping
dynamics.

ChemMaster wires MOMAP via three tools:

- ``tvcf_rate``  : compute k_r (or k_p with SOC input) using TVCF
- ``tvcf_spec``  : vibrationally resolved emission / absorption spectrum
- ``parse_output`` : harvest rates / spectra from a finished MOMAP job

MOMAP requires the user to have a license + binary installed. It expects:
- Gaussian (or BDF / ORCA) frequency & normal-mode files for the two electronic
  states involved (S0 + S1 for k_r, S0 + T1 + SOC for k_p)
- A control file (.in / momap.inp) describing temperature, range, line shape,
  Duschinsky on/off, and TVCF integration parameters

Because MOMAP input format is nontrivial and version-dependent, this wrapper:
- Generates a *template* control file using documented keywords
- Drives ``momap`` via subprocess
- Parses the standard output for k_r, FWHM, peak positions

Where MOMAP is not installed (the common state during ChemMaster development),
the tools return ENGINE_NOT_FOUND with a helpful suggestion. The dry_run flag
on each tool returns the would-be input file without invoking the binary,
useful for testing and for the documentation generator.
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
mcp = FastMCP("chem.calc_momap")


# ══════════════════════════════════════════════════════════════════════════════
# Engine detection
# ══════════════════════════════════════════════════════════════════════════════


def _check_engine() -> tuple[str | None, str | None, str | None]:
    """Return (binary, version, MOMAPHOME) or (None, None, None)."""
    from chemaster.mcp._common import probe_binary
    path, version = probe_binary(
        ("momap", "MOMAP"), version_args=["--version"],
        version_regex=r"MOMAP[^\d]*(\d+\.\d+(?:\.\d+)?)",
    )
    if not path:
        return None, None, None
    return path, version, (os.environ.get("MOMAPHOME")
                           or os.environ.get("MOMAP_HOME"))


def _engine_unavailable_response() -> dict[str, Any]:
    return {
        "ok": False,
        "error_code": "ENGINE_NOT_FOUND",
        "details": "MOMAP binary not on PATH.",
        "suggestion": (
            "MOMAP is academic-licensed (https://momap.chem-i.com). Install it, "
            "set MOMAPHOME, and add $MOMAPHOME/bin to PATH. ChemMaster will "
            "auto-detect once `momap` is callable. For testing without the "
            "engine, use dry_run=True on any tool to inspect the generated "
            "input file."
        ),
    }


# ══════════════════════════════════════════════════════════════════════════════
# Input file generation
# ══════════════════════════════════════════════════════════════════════════════


def _build_tvcf_rate_input(
    *,
    state_initial: str,         # 'S1' / 'T1'
    state_final: str,           # 'S0'
    freq_file_initial: str,     # path to Gaussian/BDF freq output for upper state
    freq_file_final: str,       # path to Gaussian/BDF freq output for lower state
    transition_dipole: list[float] | None = None,  # x,y,z in a.u.
    soc_matrix_element: float | None = None,       # cm-1, for k_p
    energy_gap_eV: float = 0.0,                    # adiabatic gap E(initial) - E(final)
    temperature_K: float = 298.15,
    duschinsky: bool = True,
    fwhm_cm_inv: float = 100.0,
    integration_time_ps: float = 5.0,
    n_grid_points: int = 8192,
) -> str:
    """Generate MOMAP TVCF rate-calculation input file (text).

    The format below follows the MOMAP user manual's "rate" task layout.
    Real MOMAP input format may evolve between versions; we use the v0.4-style
    keywords which are supported in modern releases.
    """
    rate_type = "kp" if soc_matrix_element is not None else "kr"
    edip_block = ""
    if transition_dipole is not None and len(transition_dipole) == 3:
        edip_block = (
            "transition_dipole\n"
            f"  {transition_dipole[0]:.6f} {transition_dipole[1]:.6f} {transition_dipole[2]:.6f}\n"
            "end\n"
        )
    soc_block = ""
    if soc_matrix_element is not None:
        soc_block = f"soc_matrix_element {soc_matrix_element:.6f}  ! cm^-1\n"
    return (
        f"&control\n"
        f"  task           = 'TVCF_rate'\n"
        f"  rate_type      = '{rate_type}'\n"
        f"  state_initial  = '{state_initial}'\n"
        f"  state_final    = '{state_final}'\n"
        f"  duschinsky     = {'.true.' if duschinsky else '.false.'}\n"
        f"  temperature    = {temperature_K:.2f}\n"
        f"  energy_gap_eV  = {energy_gap_eV:.6f}\n"
        f"  fwhm_cm_inv    = {fwhm_cm_inv:.2f}\n"
        f"  integration_ps = {integration_time_ps:.2f}\n"
        f"  n_grid         = {n_grid_points}\n"
        f"/\n"
        f"\n"
        f"&files\n"
        f"  freq_file_initial = '{freq_file_initial}'\n"
        f"  freq_file_final   = '{freq_file_final}'\n"
        f"/\n"
        f"\n"
        f"{edip_block}"
        f"{soc_block}"
    )


def _build_tvcf_spec_input(
    *,
    state_initial: str,
    state_final: str,
    freq_file_initial: str,
    freq_file_final: str,
    energy_gap_eV: float,
    transition_dipole: list[float] | None = None,
    temperature_K: float = 298.15,
    duschinsky: bool = True,
    spectrum_range_eV: tuple[float, float] = (0.5, 5.0),
    n_points: int = 4096,
    fwhm_cm_inv: float = 200.0,
    spectrum_type: str = "emission",  # 'emission' | 'absorption'
) -> str:
    edip_block = ""
    if transition_dipole is not None and len(transition_dipole) == 3:
        edip_block = (
            "transition_dipole\n"
            f"  {transition_dipole[0]:.6f} {transition_dipole[1]:.6f} {transition_dipole[2]:.6f}\n"
            "end\n"
        )
    return (
        f"&control\n"
        f"  task           = 'TVCF_spec'\n"
        f"  spectrum_type  = '{spectrum_type}'\n"
        f"  state_initial  = '{state_initial}'\n"
        f"  state_final    = '{state_final}'\n"
        f"  duschinsky     = {'.true.' if duschinsky else '.false.'}\n"
        f"  temperature    = {temperature_K:.2f}\n"
        f"  energy_gap_eV  = {energy_gap_eV:.6f}\n"
        f"  emin_eV        = {spectrum_range_eV[0]:.4f}\n"
        f"  emax_eV        = {spectrum_range_eV[1]:.4f}\n"
        f"  npoints        = {n_points}\n"
        f"  fwhm_cm_inv    = {fwhm_cm_inv:.2f}\n"
        f"/\n"
        f"\n"
        f"&files\n"
        f"  freq_file_initial = '{freq_file_initial}'\n"
        f"  freq_file_final   = '{freq_file_final}'\n"
        f"/\n"
        f"\n"
        f"{edip_block}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# Output parsing
# ══════════════════════════════════════════════════════════════════════════════


def _parse_rate(stdout: str) -> dict[str, Any]:
    """Extract rate constant + lifetime from MOMAP TVCF rate output."""
    out: dict[str, Any] = {}
    # k_r / k_p / k_isc / k_risc lines (different MOMAP versions print these
    # under slightly different labels; we handle a few).
    rate_patterns = [
        (r"radiative\s+rate\s+constant\s*[:=]\s*([\d.Ee+-]+)\s*s\^?-?1", "k_r_s_inv"),
        (r"phosphorescence\s+rate\s*[:=]\s*([\d.Ee+-]+)\s*s\^?-?1", "k_p_s_inv"),
        (r"k_?r\s*=\s*([\d.Ee+-]+)\s*s\^?-?1", "k_r_s_inv"),
        (r"k_?p\s*=\s*([\d.Ee+-]+)\s*s\^?-?1", "k_p_s_inv"),
        (r"k_?isc\s*=\s*([\d.Ee+-]+)\s*s\^?-?1", "k_isc_s_inv"),
        (r"k_?risc\s*=\s*([\d.Ee+-]+)\s*s\^?-?1", "k_risc_s_inv"),
        (r"k_?ic\s*=\s*([\d.Ee+-]+)\s*s\^?-?1", "k_ic_s_inv"),
    ]
    for pattern, key in rate_patterns:
        m = re.search(pattern, stdout, re.IGNORECASE)
        if m and key not in out:
            out[key] = float(m.group(1))

    # Lifetime
    m = re.search(r"lifetime\s*[:=]\s*([\d.Ee+-]+)\s*(s|ms|us|ns|ps|fs)",
                  stdout, re.IGNORECASE)
    if m:
        val = float(m.group(1))
        unit = m.group(2).lower()
        scale = {"s": 1, "ms": 1e-3, "us": 1e-6, "ns": 1e-9,
                 "ps": 1e-12, "fs": 1e-15}.get(unit, 1)
        out["lifetime_s"] = val * scale

    # Reorganization energy (commonly reported)
    m = re.search(r"reorganization\s+energy\s*[:=]\s*([\d.E+-]+)\s*(eV|cm-1|meV)",
                  stdout, re.IGNORECASE)
    if m:
        out["reorganization_energy"] = {"value": float(m.group(1)),
                                         "unit": m.group(2)}
    return out


def _parse_spectrum(stdout: str, workdir: Path) -> dict[str, Any]:
    """Find the spectrum data file MOMAP writes and load peak info."""
    # MOMAP typically writes spectrum.dat or spec_*.dat in the workdir.
    candidates = list(workdir.glob("*spec*.dat")) + list(workdir.glob("spectrum.dat"))
    if not candidates:
        return {"spectrum_data": None, "n_points": 0, "peaks": []}
    spec_file = candidates[0]
    try:
        data_text = spec_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {"spectrum_data": None}
    energies, intensities = [], []
    for line in data_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            try:
                energies.append(float(parts[0]))
                intensities.append(float(parts[1]))
            except ValueError:
                continue
    peaks = []
    if intensities:
        # Naive peak finding: local maxima above 10% of global max
        cutoff = 0.1 * max(intensities)
        for i in range(1, len(intensities) - 1):
            if (intensities[i] > intensities[i - 1] and
                    intensities[i] > intensities[i + 1] and
                    intensities[i] > cutoff):
                peaks.append({"energy": energies[i], "intensity": intensities[i]})
    return {
        "spectrum_data": str(spec_file),
        "n_points": len(energies),
        "peaks": peaks[:10],  # first 10
    }


# ══════════════════════════════════════════════════════════════════════════════
# Tools
# ══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
def tvcf_rate(
    state_initial: str,
    state_final: str,
    freq_file_initial: str,
    freq_file_final: str,
    energy_gap_eV: float,
    transition_dipole_x: float = 0.0,
    transition_dipole_y: float = 0.0,
    transition_dipole_z: float = 0.0,
    soc_matrix_element_cm_inv: float = 0.0,
    temperature_K: float = 298.15,
    duschinsky: bool = True,
    fwhm_cm_inv: float = 100.0,
    integration_time_ps: float = 5.0,
    n_grid_points: int = 8192,
    workdir: str = "",
    timeout_s: int = 7200,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Compute a TVCF rate constant (k_r for fluorescence, k_p for phosphorescence).

    For ``k_r``: pass transition_dipole_{x,y,z} (S0->S1 in a.u.); leave SOC = 0.
    For ``k_p``: pass soc_matrix_element_cm_inv (T1->S0); transition_dipole optional.

    Args:
        state_initial: 'S1' / 'T1' / etc.
        state_final: 'S0' typically.
        freq_file_*: paths to Gaussian/BDF frequency output for the two states.
        energy_gap_eV: adiabatic energy gap E(initial) - E(final), in eV.
        dry_run: if True, return the would-be input without invoking momap.

    Returns:
        ok=True: {ok, result: {k_r_s_inv | k_p_s_inv, lifetime_s, ...}, ...}
        ok=False: ENGINE_NOT_FOUND | TIMEOUT | MOMAP_RUNTIME_ERROR
    """
    use_dipole = (transition_dipole_x or transition_dipole_y or transition_dipole_z)
    use_soc = soc_matrix_element_cm_inv > 0
    inp = _build_tvcf_rate_input(
        state_initial=state_initial,
        state_final=state_final,
        freq_file_initial=freq_file_initial,
        freq_file_final=freq_file_final,
        transition_dipole=([transition_dipole_x, transition_dipole_y,
                            transition_dipole_z] if use_dipole else None),
        soc_matrix_element=(soc_matrix_element_cm_inv if use_soc else None),
        energy_gap_eV=energy_gap_eV,
        temperature_K=temperature_K,
        duschinsky=duschinsky,
        fwhm_cm_inv=fwhm_cm_inv,
        integration_time_ps=integration_time_ps,
        n_grid_points=n_grid_points,
    )

    if dry_run:
        return {"ok": True,
                "result": {"input_file_text": inp,
                           "rate_type": "k_p" if use_soc else "k_r"},
                "warnings": [{"code": "DRY_RUN",
                               "message": "MOMAP not invoked"}],
                "meta": {"dry_run": True}}

    momap_path, version, _ = _check_engine()
    if momap_path is None:
        return _engine_unavailable_response()

    wd = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="momap_rate_"))
    wd.mkdir(parents=True, exist_ok=True)
    inp_path = wd / "momap.inp"
    inp_path.write_text(inp, encoding="ascii")

    wall_start = time.time()
    try:
        proc = subprocess.run(
            [momap_path, str(inp_path)],
            cwd=wd, capture_output=True, text=True, timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error_code": "TIMEOUT",
                "details": f"MOMAP exceeded {timeout_s}s",
                "meta": {"momap_version": version, "workdir": str(wd)}}
    if proc.returncode != 0:
        return {"ok": False, "error_code": "MOMAP_RUNTIME_ERROR",
                "details": (proc.stderr or proc.stdout)[-1500:],
                "suggestion": ("Check freq_file paths exist and match the "
                                "expected Gaussian/BDF format. Verify "
                                "transition_dipole / soc parameters are sane."),
                "meta": {"momap_version": version, "workdir": str(wd)}}

    rate_data = _parse_rate(proc.stdout or "")
    return {
        "ok": True,
        "result": {
            **rate_data,
            "rate_type": "k_p" if use_soc else "k_r",
            "state_initial": state_initial, "state_final": state_final,
            "energy_gap_eV": energy_gap_eV, "temperature_K": temperature_K,
        },
        "warnings": [] if rate_data else [{"code": "PARSE_INCOMPLETE",
                                            "message": "Could not extract rate from output; check raw log"}],
        "meta": {"momap_version": version, "workdir": str(wd),
                 "wall_time_s": round(time.time() - wall_start, 1)},
    }


@mcp.tool()
def tvcf_spec(
    state_initial: str,
    state_final: str,
    freq_file_initial: str,
    freq_file_final: str,
    energy_gap_eV: float,
    transition_dipole_x: float = 0.0,
    transition_dipole_y: float = 0.0,
    transition_dipole_z: float = 0.0,
    spectrum_type: str = "emission",
    temperature_K: float = 298.15,
    duschinsky: bool = True,
    emin_eV: float = 0.5,
    emax_eV: float = 5.0,
    n_points: int = 4096,
    fwhm_cm_inv: float = 200.0,
    workdir: str = "",
    timeout_s: int = 7200,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Compute a vibrationally resolved emission or absorption spectrum."""
    use_dipole = (transition_dipole_x or transition_dipole_y or transition_dipole_z)
    inp = _build_tvcf_spec_input(
        state_initial=state_initial, state_final=state_final,
        freq_file_initial=freq_file_initial, freq_file_final=freq_file_final,
        energy_gap_eV=energy_gap_eV,
        transition_dipole=([transition_dipole_x, transition_dipole_y,
                            transition_dipole_z] if use_dipole else None),
        temperature_K=temperature_K, duschinsky=duschinsky,
        spectrum_range_eV=(emin_eV, emax_eV),
        n_points=n_points, fwhm_cm_inv=fwhm_cm_inv,
        spectrum_type=spectrum_type,
    )
    if dry_run:
        return {"ok": True,
                "result": {"input_file_text": inp,
                           "spectrum_type": spectrum_type},
                "warnings": [{"code": "DRY_RUN",
                              "message": "MOMAP not invoked"}],
                "meta": {"dry_run": True}}

    momap_path, version, _ = _check_engine()
    if momap_path is None:
        return _engine_unavailable_response()

    wd = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="momap_spec_"))
    wd.mkdir(parents=True, exist_ok=True)
    inp_path = wd / "momap.inp"
    inp_path.write_text(inp, encoding="ascii")

    wall_start = time.time()
    try:
        proc = subprocess.run(
            [momap_path, str(inp_path)],
            cwd=wd, capture_output=True, text=True, timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error_code": "TIMEOUT",
                "details": f"MOMAP exceeded {timeout_s}s",
                "suggestion": "Increase timeout_s; spectrum grids with many "
                              "points integrate slowly."}
    if proc.returncode != 0:
        return {"ok": False, "error_code": "MOMAP_RUNTIME_ERROR",
                "details": (proc.stderr or proc.stdout)[-1500:],
                "suggestion": "Inspect the MOMAP output tail; run with "
                              "dry_run=True to check the generated .inp "
                              "against your MOMAP version's manual."}
    spec_data = _parse_spectrum(proc.stdout or "", wd)

    return {
        "ok": True,
        "result": {
            **spec_data,
            "spectrum_type": spectrum_type,
            "state_initial": state_initial, "state_final": state_final,
            "energy_gap_eV": energy_gap_eV,
        },
        "warnings": [] if spec_data.get("n_points") else
                     [{"code": "NO_SPECTRUM_DATA",
                       "message": "Spectrum file not found in workdir"}],
        "meta": {"momap_version": version, "workdir": str(wd),
                 "wall_time_s": round(time.time() - wall_start, 1)},
    }


@mcp.tool()
def parse_output(output_path: str) -> dict[str, Any]:
    """Parse an existing MOMAP output file (run elsewhere) for rates and spectra.

    Useful when the user has run MOMAP outside ChemMaster (e.g. on a HPC) and
    wants ChemMaster to harvest results without re-running the calculation.
    """
    p = Path(output_path)
    if not p.is_file():
        return {"ok": False, "error_code": "FILE_NOT_FOUND",
                "details": f"{p} does not exist",
                "suggestion": "Pass the absolute path to the MOMAP .log/.out "
                              "file (e.g. fetched back from HPC via "
                              "hpc_fetch)."}
    text = p.read_text(encoding="utf-8", errors="replace")
    rate_data = _parse_rate(text)
    spec_data = _parse_spectrum(text, p.parent)
    return {
        "ok": True,
        "result": {**rate_data, **spec_data, "source_file": str(p)},
        "warnings": [],
        "meta": {"file_size_bytes": p.stat().st_size},
    }


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
