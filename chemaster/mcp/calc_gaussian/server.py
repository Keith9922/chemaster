"""chem.calc_gaussian — Gaussian (g16) input parsing + subprocess driver.

Two tools:

- ``parse_input`` reads a Gaussian ``.com`` / ``.gjf`` file and returns
  a structured representation: route keywords, link0 settings, charge /
  multiplicity, geometry (xyz), and the inferred *task type*
  (sp / opt / freq / opt_freq / td / td_opt / td_freq / nacme / soc /
  scan / mixed). This is what the agent uses to read user-supplied
  Gaussian inputs (e.g. the師姐 momap-jingti dataset) and plan the
  equivalent ChemMaster workflow.

- ``run`` drives the ``g16`` binary on a parsed-or-built input. Falls
  back to ENGINE_NOT_FOUND with a clear message when Gaussian isn't on
  PATH (which is the normal state — Gaussian is commercial; psi4/ORCA
  are the open-source defaults).

The parser is the higher-value piece: it lets the agent *understand*
Gaussian inputs (the师姐 reference data is all Gaussian-format) without
needing Gaussian itself.
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
mcp = FastMCP("chem.calc_gaussian")


# ══════════════════════════════════════════════════════════════════════════════
# Engine
# ══════════════════════════════════════════════════════════════════════════════


def _check_engine() -> tuple[str | None, str | None]:
    """Return (g16 / g09 path, version) or (None, None)."""
    for cand in ("g16", "g09"):
        path = shutil.which(cand)
        if path:
            return path, cand
    return None, None


# ══════════════════════════════════════════════════════════════════════════════
# .com / .gjf parser
# ══════════════════════════════════════════════════════════════════════════════


_LINK0_RE = re.compile(r"^%(\w+)\s*=\s*(.+)\s*$")


def _split_blocks(text: str) -> list[list[str]]:
    """Gaussian inputs are separated by blank lines into blocks:

      0: link0 commands (%chk, %mem, %nproc, ...)         (optional)
      1: route line(s)  (#p ...)
      2: title          (single line)
      3: charge multiplicity + geometry
      4...: connectivity / parameters (optional)
    """
    lines = text.splitlines()
    blocks: list[list[str]] = [[]]
    for ln in lines:
        if ln.strip() == "":
            if blocks[-1]:
                blocks.append([])
        else:
            blocks[-1].append(ln.rstrip())
    return [b for b in blocks if b]


def _classify_route(route: str) -> dict[str, Any]:
    """Inspect the Gaussian # route line and infer the task type."""
    r = route.lower()
    has_opt = bool(re.search(r"\bopt\b", r))
    has_freq = bool(re.search(r"\bfreq\b", r))
    has_td = bool(re.search(r"\btd\b\s*(?:\(|=)", r) or re.search(r"^td\b", r) or " td " in r)
    has_td_simple = bool(re.search(r"^\s*#p?\s+td\b", r) or " td/" in r or " td " in r)
    has_nacme = bool(re.search(r"prop\s*=\s*field|iop\(6/22|nacme", r))
    has_field = "prop=field" in r.replace(" ", "")
    is_triplet = "td(triplet" in r.replace(" ", "") or "triplet" in r
    is_singlet = "td(singlet" in r.replace(" ", "") or (has_td and not is_triplet)
    has_scan = "scan" in r
    has_irc = "irc" in r
    has_ts = bool(re.search(r"\bts\b", r)) or "calcfc" in r
    has_em = "em=gd3bj" in r or "empiricaldispersion" in r
    has_solvent = bool(re.search(r"scrf|cpcm|pcm|smd", r))

    # Pick a primary task label
    if has_nacme or has_field:
        task = "nacme"
    elif has_td and has_opt and has_freq:
        task = "td_opt_freq"
    elif has_td and has_opt:
        task = "td_opt"
    elif has_td and has_freq:
        task = "td_freq"
    elif has_td:
        task = "td_sp"
    elif has_opt and has_freq:
        task = "opt_freq"
    elif has_opt:
        task = "opt"
    elif has_freq:
        task = "freq"
    elif has_irc:
        task = "irc"
    elif has_scan:
        task = "scan"
    else:
        task = "sp"

    # Method / basis
    method = None
    basis = None
    m = re.search(r"#p?\s+(?:\S+\s+)?([A-Za-z0-9\(\),\-]+)\s*/\s*(\S+)", route)
    if m:
        method = m.group(1)
        basis = m.group(2).rstrip(",")
    return {
        "task": task,
        "method": method,
        "basis": basis,
        "has_opt": has_opt,
        "has_freq": has_freq,
        "has_td": has_td,
        "has_nacme": has_nacme,
        "is_triplet": is_triplet and has_td,
        "is_singlet": is_singlet and has_td,
        "has_scan": has_scan,
        "has_irc": has_irc,
        "has_ts": has_ts,
        "has_dispersion": has_em,
        "has_solvent": has_solvent,
    }


def _parse_geometry(block: list[str]) -> tuple[int, int, str]:
    """The first non-route block after title contains charge/mult and atoms."""
    if not block:
        return 0, 1, ""
    head = block[0].split()
    try:
        charge = int(head[0])
        mult = int(head[1])
        atom_lines = block[1:]
    except (ValueError, IndexError):
        return 0, 1, ""
    coords: list[str] = []
    for ln in atom_lines:
        parts = ln.split()
        if len(parts) >= 4:
            sym = parts[0]
            x, y, z = parts[-3:]
            coords.append(f"{sym} {x} {y} {z}")
    n = len(coords)
    xyz = f"{n}\nFrom Gaussian input\n" + "\n".join(coords) + "\n"
    return charge, mult, xyz


@mcp.tool()
def parse_input(file_path: str) -> dict[str, Any]:
    """Parse a Gaussian .com / .gjf input file.

    Returns a structured representation: link0 commands, route line, task
    type (sp / opt / opt_freq / td_sp / td_opt / td_opt_freq / nacme /
    irc / scan), method, basis, charge, multiplicity, n_atoms, geometry
    (standard xyz with atom count + comment header), and a list of "tasks
    this would create in ChemMaster".

    When to use:
        - User hands you a Gaussian input file (e.g. the師姐 momap-jingti
          benchmark) and you need to understand what calculation it
          represents.
        - Before deciding which ChemMaster MCP tools to chain, parse the
          input to recover the workflow shape.

    When NOT to use:
        - If the user already has a parsed structure (xyz + method + basis).

    Returns:
        ok=True:
          {ok, result: {link0: {chk, mem, nproc, ...},
                        route: str,
                        task: str,
                        method, basis,
                        charge, multiplicity, n_atoms,
                        geometry_xyz, formula,
                        suggested_chemmaster_workflow: [...]}, ...}
        ok=False:
          {ok=False, error_code: FILE_NOT_FOUND | PARSE_ERROR, ...}
    """
    p = Path(file_path)
    if not p.is_file():
        return {
            "ok": False,
            "error_code": "FILE_NOT_FOUND",
            "details": f"{file_path} not readable.",
            "suggestion": "Pass an absolute path to a .com or .gjf file.",
        }
    try:
        text = p.read_text(errors="replace")
    except Exception as exc:
        return {"ok": False, "error_code": "PARSE_ERROR", "details": str(exc),
                "suggestion": "Check file encoding (Gaussian inputs are normally ASCII)."}

    blocks = _split_blocks(text)
    if not blocks:
        return {"ok": False, "error_code": "PARSE_ERROR",
                "details": "empty input", "suggestion": "Inspect the file."}

    # The first block normally contains both link0 (%-lines) and the route
    # (#-lines). Gaussian doesn't require a blank line between them. Split
    # on prefix.
    link0: dict[str, str] = {}
    block_iter = iter(blocks)
    first_block = next(block_iter)
    link0_lines: list[str] = []
    route_lines: list[str] = []
    for ln in first_block:
        if ln.lstrip().startswith("%"):
            link0_lines.append(ln)
        else:
            route_lines.append(ln)
    for ln in link0_lines:
        m = _LINK0_RE.match(ln)
        if m:
            link0[m.group(1).lower()] = m.group(2)

    # If the first block held only link0 (rare but seen with blank separators),
    # the route is in the next block.
    if not route_lines:
        try:
            route_lines = next(block_iter)
        except StopIteration:
            return {"ok": False, "error_code": "PARSE_ERROR",
                    "details": "no route block", "suggestion": "Add a # ... line."}
    route = " ".join(route_lines).strip()

    # Title
    try:
        title_block = next(block_iter)
        title = " ".join(title_block).strip()
    except StopIteration:
        title = ""

    # Geometry block
    try:
        geom_block = next(block_iter)
    except StopIteration:
        geom_block = []

    classified = _classify_route(route)
    charge, mult, xyz = _parse_geometry(geom_block)

    # Formula
    elements: list[str] = [ln.split()[0] for ln in xyz.splitlines()[2:] if ln.strip()]
    counts: dict[str, int] = {}
    for el in elements:
        counts[el] = counts.get(el, 0) + 1
    formula = "".join(f"{el}{counts[el] if counts[el] > 1 else ''}"
                     for el in sorted(counts))

    # Suggested ChemMaster workflow (rough mapping)
    workflow: list[dict[str, str]] = []
    task = classified["task"]
    if task in ("opt", "opt_freq"):
        workflow.append({"tool": "calc_psi4_optimize",
                         "rationale": "DFT geometry optimization"})
    if task in ("opt_freq", "freq"):
        workflow.append({"tool": "calc_psi4_frequency",
                         "rationale": "harmonic frequencies + thermal corrections"})
    if task in ("td_sp", "td_opt", "td_opt_freq", "td_freq"):
        workflow.append({"tool": "calc_psi4_tddft",
                         "rationale": "TDDFT excited states (vertical)"})
    if task in ("td_opt", "td_opt_freq"):
        workflow.append({"tool": "calc_psi4_optimize  (excited-state TODO)",
                         "rationale": "Excited-state geometry optimization "
                                       "is not yet exposed as a separate "
                                       "MCP tool — Gaussian's TD opt is "
                                       "still a roadmap item."})
    if task == "nacme":
        workflow.append({"tool": "(none yet)",
                         "rationale": "NACME (non-adiabatic coupling matrix "
                                       "elements) is not implemented in any "
                                       "current ChemMaster MCP. Roadmap."})
    if task == "td_freq" and "triplet" in route.lower():
        workflow.append({"tool": "calc_bdf_soc",
                         "rationale": "Triplet-state info is consumed by "
                                       "the SOC step in the TADF pipeline."})

    return {
        "ok": True,
        "result": {
            "file_path": str(p),
            "link0": link0,
            "route": route,
            "title": title,
            "task": task,
            "method": classified["method"],
            "basis": classified["basis"],
            "has_opt": classified["has_opt"],
            "has_freq": classified["has_freq"],
            "has_td": classified["has_td"],
            "has_nacme": classified["has_nacme"],
            "is_triplet_td": classified["is_triplet"],
            "has_dispersion": classified["has_dispersion"],
            "has_solvent": classified["has_solvent"],
            "charge": charge,
            "multiplicity": mult,
            "n_atoms": len(elements),
            "formula": formula,
            "geometry_xyz": xyz,
            "suggested_chemmaster_workflow": workflow,
        },
        "warnings": (
            ["geometry block was empty — only the route was parsed"]
            if not elements else []
        ),
        "meta": {"parser_version": "0.1"},
    }


# ══════════════════════════════════════════════════════════════════════════════
# run (subprocess to g16)
# ══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
def run(input_file: str, timeout_s: int = 7200) -> dict[str, Any]:
    """Drive g16 / g09 on a Gaussian input file.

    Use only when Gaussian is installed (commercial software). For most
    ChemMaster workflows, prefer calc_psi4_* / calc_orca_* / calc_xtb_*.

    Returns:
        ok=True: {ok, result: {output_path, log_excerpt}, ...}
        ok=False: ENGINE_NOT_FOUND | TIMEOUT | NONZERO_RETURN
    """
    g_path, g_name = _check_engine()
    if not g_path:
        return {
            "ok": False,
            "error_code": "ENGINE_NOT_FOUND",
            "details": "g16 / g09 binary not on PATH.",
            "suggestion": (
                "Gaussian is commercial; install your site licence and "
                "make sure g16 is on PATH. For open-source alternatives "
                "use calc_psi4_* or calc_orca_*."
            ),
        }
    inp = Path(input_file)
    if not inp.is_file():
        return {"ok": False, "error_code": "FILE_NOT_FOUND",
                "details": str(inp), "suggestion": "Pass an absolute path."}

    log_path = inp.with_suffix(".log")
    wall_start = time.time()
    try:
        proc = subprocess.run(
            [g_path, str(inp)], cwd=inp.parent,
            capture_output=True, text=True, timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error_code": "TIMEOUT",
                "details": f"g16 exceeded {timeout_s}s",
                "suggestion": "Pre-screen with xTB; reduce basis."}
    if proc.returncode != 0:
        return {
            "ok": False,
            "error_code": "NONZERO_RETURN",
            "details": (proc.stderr or proc.stdout)[-1500:],
            "suggestion": "Inspect the .log for the full traceback.",
            "meta": {"engine": g_name, "returncode": proc.returncode,
                     "wall_time_s": round(time.time() - wall_start, 1)},
        }
    excerpt = ""
    try:
        excerpt = log_path.read_text(errors="replace")[-2000:]
    except Exception:
        pass
    return {
        "ok": True,
        "result": {"output_path": str(log_path), "log_excerpt": excerpt},
        "warnings": [],
        "meta": {"engine": g_name,
                 "wall_time_s": round(time.time() - wall_start, 1)},
    }


# ══════════════════════════════════════════════════════════════════════════════
# v3.0: structured calculation tools (optimize / frequency / tddft / etc.)
#
# These wrap the generic parse_input/run pair into typed, single-purpose
# entry points the agent can call without hand-crafting Gaussian input
# strings. Each tool:
#   1. Builds a Gaussian .com from xyz + method + basis + task-specific knobs
#   2. Drives g16 via the existing run() helper
#   3. Parses the .log for the relevant numbers (energy / freqs / excited states)
#
# When g16 is unavailable, tools return ENGINE_NOT_FOUND (same as run()).
# ══════════════════════════════════════════════════════════════════════════════


def _xyz_to_gaussian_geom(xyz: str, charge: int, multiplicity: int) -> str:
    """Convert standard xyz block into Gaussian "charge mult\\n<atoms>" form."""
    lines = [ln for ln in xyz.strip().splitlines() if ln.strip()]
    try:
        n_atoms = int(lines[0].strip())
        atom_lines = lines[2 : 2 + n_atoms]
    except ValueError:
        atom_lines = lines
    coords = "\n".join(atom_lines)
    return f"{charge} {multiplicity}\n{coords}\n"


def _build_input(
    *,
    route: str,
    geom_block: str,
    title: str = "ChemMaster Gaussian job",
    nproc: int = 4,
    mem: str = "4GB",
    chk: str | None = None,
) -> str:
    """Compose a complete Gaussian .com text from route + geometry."""
    link0 = [f"%nprocshared={nproc}", f"%mem={mem}"]
    if chk:
        link0.append(f"%chk={chk}")
    parts = [
        "\n".join(link0),
        route.strip(),
        "",
        title,
        "",
        geom_block.strip(),
        "",
        "",
    ]
    return "\n".join(parts)


def _parse_scf_energy(log_text: str) -> float | None:
    """Extract final SCF energy from Gaussian log."""
    matches = re.findall(r"SCF Done:\s+E\([^)]+\)\s*=\s*(-?\d+\.\d+)", log_text)
    if matches:
        return float(matches[-1])
    return None


def _parse_optimized_xyz(log_text: str) -> str | None:
    """Extract the last "Standard orientation" block as xyz text."""
    blocks = re.findall(
        r"Standard orientation:.*?\n.*?\n.*?\n.*?\n.*?\n(.*?)\n\s*-+",
        log_text,
        re.DOTALL,
    )
    if not blocks:
        # Try input orientation as fallback
        blocks = re.findall(
            r"Input orientation:.*?\n.*?\n.*?\n.*?\n.*?\n(.*?)\n\s*-+",
            log_text,
            re.DOTALL,
        )
    if not blocks:
        return None
    last = blocks[-1].strip().splitlines()
    z_to_sym = {
        1: "H", 2: "He", 3: "Li", 4: "Be", 5: "B", 6: "C", 7: "N", 8: "O",
        9: "F", 10: "Ne", 11: "Na", 12: "Mg", 13: "Al", 14: "Si", 15: "P",
        16: "S", 17: "Cl", 18: "Ar", 19: "K", 20: "Ca", 26: "Fe", 29: "Cu",
        30: "Zn", 35: "Br", 53: "I",
    }
    atom_lines = []
    for line in last:
        parts = line.split()
        if len(parts) >= 6:
            try:
                z = int(parts[1])
                x, y, zc = float(parts[3]), float(parts[4]), float(parts[5])
                sym = z_to_sym.get(z, f"X{z}")
                atom_lines.append(f"{sym} {x:.6f} {y:.6f} {zc:.6f}")
            except ValueError:
                continue
    if not atom_lines:
        return None
    return f"{len(atom_lines)}\nGaussian optimized geometry\n" + "\n".join(atom_lines)


def _parse_frequencies(log_text: str) -> list[float]:
    """Extract harmonic frequencies (cm^-1)."""
    freqs: list[float] = []
    for m in re.finditer(r"Frequencies\s+--\s+(.+)", log_text):
        line = m.group(1)
        for tok in line.split():
            try:
                freqs.append(float(tok))
            except ValueError:
                pass
    return freqs


def _parse_thermal(log_text: str) -> dict[str, float]:
    """Extract ZPE, thermal corrections, free energy."""
    out: dict[str, float] = {}
    patterns = {
        "zpe_Hartree": r"Zero-point correction=\s+(-?\d+\.\d+)",
        "thermal_E_Hartree": r"Thermal correction to Energy=\s+(-?\d+\.\d+)",
        "thermal_H_Hartree": r"Thermal correction to Enthalpy=\s+(-?\d+\.\d+)",
        "thermal_G_Hartree": r"Thermal correction to Gibbs Free Energy=\s+(-?\d+\.\d+)",
        "sum_E_zpe_Hartree": r"Sum of electronic and zero-point Energies=\s+(-?\d+\.\d+)",
        "sum_E_thermal_Hartree": r"Sum of electronic and thermal Energies=\s+(-?\d+\.\d+)",
        "sum_H_thermal_Hartree": r"Sum of electronic and thermal Enthalpies=\s+(-?\d+\.\d+)",
        "sum_G_thermal_Hartree": r"Sum of electronic and thermal Free Energies=\s+(-?\d+\.\d+)",
    }
    for key, pat in patterns.items():
        m = re.search(pat, log_text)
        if m:
            out[key] = float(m.group(1))
    return out


def _parse_excited_states(log_text: str) -> list[dict[str, Any]]:
    """Extract TDDFT excited-state info from Gaussian output."""
    states: list[dict[str, Any]] = []
    pattern = re.compile(
        r"Excited State\s+(\d+):\s+(\S+)\s+(-?\d+\.\d+)\s+eV\s+"
        r"(-?\d+\.\d+)\s+nm\s+f=(\d+\.\d+)"
    )
    for m in pattern.finditer(log_text):
        states.append({
            "state": int(m.group(1)),
            "spin_label": m.group(2),
            "energy_eV": float(m.group(3)),
            "wavelength_nm": float(m.group(4)),
            "oscillator_strength": float(m.group(5)),
        })
    return states


def _execute_gaussian_job(
    input_text: str,
    workdir: Path,
    job_name: str,
    timeout_s: int,
) -> tuple[bool, str, str]:
    """Drive g16 on a generated input. Returns (ok, stdout_path, stderr)."""
    g_path, g_name = _check_engine()
    if not g_path:
        return False, "", "ENGINE_NOT_FOUND"

    workdir.mkdir(parents=True, exist_ok=True)
    com_path = workdir / f"{job_name}.com"
    log_path = workdir / f"{job_name}.log"
    com_path.write_text(input_text, encoding="ascii", errors="replace")

    try:
        proc = subprocess.run(
            [g_path],
            input=input_text,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            cwd=str(workdir),
        )
    except subprocess.TimeoutExpired:
        return False, str(log_path), "TIMEOUT"

    log_path.write_text(proc.stdout, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        return False, str(log_path), proc.stderr or "NONZERO_RETURN"
    return True, str(log_path), ""


@mcp.tool()
def optimize(
    geometry_xyz: str,
    method: str = "B3LYP",
    basis: str = "6-31G(d)",
    charge: int = 0,
    multiplicity: int = 1,
    dispersion: str = "GD3BJ",
    workdir: str = "",
    timeout_s: int = 7200,
) -> dict[str, Any]:
    """Run a ground-state geometry optimization in Gaussian.

    Returns:
        ok=True: {ok, result: {final_energy_Hartree, optimized_xyz, converged,
                                 wall_time_s}, meta}
        ok=False: ENGINE_NOT_FOUND | TIMEOUT | OPT_NOT_CONVERGED | ...
    """
    g_path, g_name = _check_engine()
    if not g_path:
        return {
            "ok": False, "error_code": "ENGINE_NOT_FOUND",
            "details": "g16 / g09 not on PATH",
            "suggestion": "Install Gaussian or use calc_psi4 / calc_orca.",
        }

    wd = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="chemaster_g16_opt_"))
    geom = _xyz_to_gaussian_geom(geometry_xyz, charge, multiplicity)
    disp = f" EmpiricalDispersion={dispersion}" if dispersion else ""
    route = f"#p {method}/{basis}{disp} Opt"
    inp = _build_input(route=route, geom_block=geom, title=f"opt {method}/{basis}")

    wall_start = time.time()
    ok, log_path, err = _execute_gaussian_job(inp, wd, "opt", timeout_s)
    wall = round(time.time() - wall_start, 1)
    if not ok:
        if err == "TIMEOUT":
            return {"ok": False, "error_code": "TIMEOUT",
                    "details": f"timeout after {timeout_s}s", "log_path": log_path}
        return {"ok": False, "error_code": "GAUSSIAN_FAILED",
                "details": err, "log_path": log_path}

    log_text = Path(log_path).read_text(encoding="utf-8", errors="replace")
    converged = "Stationary point found" in log_text
    energy = _parse_scf_energy(log_text)
    opt_xyz = _parse_optimized_xyz(log_text)
    warnings = []
    if not converged:
        warnings.append({"code": "OPT_NOT_CONVERGED",
                         "message": "Optimization did not reach stationary point"})

    return {
        "ok": True,
        "result": {
            "final_energy": {"value": energy, "unit": "Hartree"},
            "optimized_xyz": opt_xyz or "",
            "converged": converged,
            "method": method,
            "basis": basis,
            "wall_time_s": wall,
        },
        "warnings": warnings,
        "meta": {"engine": g_name, "log_path": log_path, "workdir": str(wd)},
    }


@mcp.tool()
def frequency(
    geometry_xyz: str,
    method: str = "B3LYP",
    basis: str = "6-31G(d)",
    charge: int = 0,
    multiplicity: int = 1,
    dispersion: str = "GD3BJ",
    temperature: float = 298.15,
    workdir: str = "",
    timeout_s: int = 7200,
) -> dict[str, Any]:
    """Run a harmonic frequency analysis in Gaussian.

    The `geometry_xyz` MUST be already optimized at the same method/basis.
    Returns frequencies (cm-1), thermal corrections, ZPE, imaginary count.
    """
    g_path, g_name = _check_engine()
    if not g_path:
        return {"ok": False, "error_code": "ENGINE_NOT_FOUND",
                "details": "g16 / g09 not on PATH"}

    wd = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="chemaster_g16_freq_"))
    geom = _xyz_to_gaussian_geom(geometry_xyz, charge, multiplicity)
    disp = f" EmpiricalDispersion={dispersion}" if dispersion else ""
    route = f"#p {method}/{basis}{disp} Freq Temperature={temperature}"
    inp = _build_input(route=route, geom_block=geom, title=f"freq {method}/{basis}")

    wall_start = time.time()
    ok, log_path, err = _execute_gaussian_job(inp, wd, "freq", timeout_s)
    wall = round(time.time() - wall_start, 1)
    if not ok:
        return {"ok": False, "error_code": "TIMEOUT" if err == "TIMEOUT" else "GAUSSIAN_FAILED",
                "details": err, "log_path": log_path}

    log_text = Path(log_path).read_text(encoding="utf-8", errors="replace")
    freqs = _parse_frequencies(log_text)
    thermal = _parse_thermal(log_text)
    n_imag = sum(1 for f in freqs if f < -10.0)
    warnings = []
    if n_imag > 0:
        warnings.append({"code": "NEGATIVE_FREQUENCIES",
                         "message": f"{n_imag} imaginary mode(s) below -10 cm-1"})

    return {
        "ok": True,
        "result": {
            "frequencies_cm_inv": freqs,
            "n_imaginary": n_imag,
            "thermal": thermal,
            "method": method,
            "basis": basis,
            "wall_time_s": wall,
        },
        "warnings": warnings,
        "meta": {"engine": g_name, "log_path": log_path, "workdir": str(wd)},
    }


@mcp.tool()
def tddft(
    geometry_xyz: str,
    method: str = "CAM-B3LYP",
    basis: str = "def2-SVP",
    charge: int = 0,
    multiplicity: int = 1,
    n_singlets: int = 5,
    n_triplets: int = 0,
    use_tda: bool = True,
    workdir: str = "",
    timeout_s: int = 7200,
) -> dict[str, Any]:
    """Run a TDDFT vertical excitation calculation.

    n_triplets > 0 routes to "TDA(50-50,nstates=N)" or "TD(50-50,nstates=N)" so
    both spin manifolds appear in the output.
    """
    g_path, g_name = _check_engine()
    if not g_path:
        return {"ok": False, "error_code": "ENGINE_NOT_FOUND",
                "details": "g16 / g09 not on PATH"}

    wd = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="chemaster_g16_tddft_"))
    geom = _xyz_to_gaussian_geom(geometry_xyz, charge, multiplicity)
    method_kw = "TDA" if use_tda else "TD"
    if n_triplets > 0:
        nstates = n_singlets + n_triplets
        td_kw = f"{method_kw}(50-50,nstates={nstates})"
    else:
        td_kw = f"{method_kw}(nstates={n_singlets})"
    route = f"#p {method}/{basis} {td_kw}"
    inp = _build_input(route=route, geom_block=geom, title=f"tddft {method}/{basis}")

    wall_start = time.time()
    ok, log_path, err = _execute_gaussian_job(inp, wd, "tddft", timeout_s)
    wall = round(time.time() - wall_start, 1)
    if not ok:
        return {"ok": False, "error_code": "TIMEOUT" if err == "TIMEOUT" else "GAUSSIAN_FAILED",
                "details": err, "log_path": log_path}

    log_text = Path(log_path).read_text(encoding="utf-8", errors="replace")
    states = _parse_excited_states(log_text)
    return {
        "ok": True,
        "result": {
            "excited_states": states,
            "n_states": len(states),
            "method": method,
            "basis": basis,
            "tda": use_tda,
            "wall_time_s": wall,
        },
        "warnings": [],
        "meta": {"engine": g_name, "log_path": log_path, "workdir": str(wd)},
    }


@mcp.tool()
def opt_excited_state(
    geometry_xyz: str,
    method: str = "CAM-B3LYP",
    basis: str = "def2-SVP",
    charge: int = 0,
    multiplicity: int = 1,
    target_state: int = 1,
    use_tda: bool = True,
    workdir: str = "",
    timeout_s: int = 14400,
) -> dict[str, Any]:
    """TD-opt: optimize a specific excited-state geometry."""
    g_path, g_name = _check_engine()
    if not g_path:
        return {"ok": False, "error_code": "ENGINE_NOT_FOUND",
                "details": "g16 / g09 not on PATH"}

    wd = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="chemaster_g16_topt_"))
    geom = _xyz_to_gaussian_geom(geometry_xyz, charge, multiplicity)
    method_kw = "TDA" if use_tda else "TD"
    route = f"#p {method}/{basis} {method_kw}(root={target_state},nstates=5) Opt"
    inp = _build_input(route=route, geom_block=geom,
                       title=f"td-opt root={target_state}")

    wall_start = time.time()
    ok, log_path, err = _execute_gaussian_job(inp, wd, "topt", timeout_s)
    wall = round(time.time() - wall_start, 1)
    if not ok:
        return {"ok": False, "error_code": "TIMEOUT" if err == "TIMEOUT" else "GAUSSIAN_FAILED",
                "details": err, "log_path": log_path}

    log_text = Path(log_path).read_text(encoding="utf-8", errors="replace")
    converged = "Stationary point found" in log_text
    states = _parse_excited_states(log_text)
    opt_xyz = _parse_optimized_xyz(log_text)
    return {
        "ok": True,
        "result": {
            "optimized_xyz": opt_xyz or "",
            "excited_states": states,
            "target_state": target_state,
            "converged": converged,
            "method": method, "basis": basis,
            "wall_time_s": wall,
        },
        "warnings": [] if converged else [{"code": "OPT_NOT_CONVERGED",
                                            "message": "TD-opt did not converge"}],
        "meta": {"engine": g_name, "log_path": log_path, "workdir": str(wd)},
    }


@mcp.tool()
def single_point(
    geometry_xyz: str,
    method: str = "B3LYP",
    basis: str = "def2-TZVP",
    charge: int = 0,
    multiplicity: int = 1,
    dispersion: str = "GD3BJ",
    workdir: str = "",
    timeout_s: int = 3600,
) -> dict[str, Any]:
    """Single-point energy at a fixed geometry."""
    g_path, g_name = _check_engine()
    if not g_path:
        return {"ok": False, "error_code": "ENGINE_NOT_FOUND",
                "details": "g16 / g09 not on PATH"}

    wd = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="chemaster_g16_sp_"))
    geom = _xyz_to_gaussian_geom(geometry_xyz, charge, multiplicity)
    disp = f" EmpiricalDispersion={dispersion}" if dispersion else ""
    route = f"#p {method}/{basis}{disp}"
    inp = _build_input(route=route, geom_block=geom, title=f"sp {method}/{basis}")

    wall_start = time.time()
    ok, log_path, err = _execute_gaussian_job(inp, wd, "sp", timeout_s)
    wall = round(time.time() - wall_start, 1)
    if not ok:
        return {"ok": False, "error_code": "TIMEOUT" if err == "TIMEOUT" else "GAUSSIAN_FAILED",
                "details": err, "log_path": log_path}

    log_text = Path(log_path).read_text(encoding="utf-8", errors="replace")
    energy = _parse_scf_energy(log_text)
    return {
        "ok": True,
        "result": {
            "final_energy": {"value": energy, "unit": "Hartree"},
            "method": method, "basis": basis,
            "wall_time_s": wall,
        },
        "warnings": [],
        "meta": {"engine": g_name, "log_path": log_path, "workdir": str(wd)},
    }


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
