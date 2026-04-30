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


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
