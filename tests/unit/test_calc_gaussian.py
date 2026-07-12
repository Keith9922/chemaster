"""calc_gaussian MCP — input parser + ENGINE_NOT_FOUND tests."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

# ──────────────────────────────────────────────────────────────────────────
# parser fixtures (small synthetic .com snippets)
# ──────────────────────────────────────────────────────────────────────────


_OPT_FREQ = """%chk=mol.chk
%mem=4GB
%nproc=4
#p B3LYP/def2-SVP opt freq em=gd3bj

water opt+freq

0 1
O 0.0 0.0 0.117
H 0.0 0.757 -0.471
H 0.0 -0.757 -0.471

"""

_TD_OPT_FREQ_SINGLET = """%chk=mol.chk
%mem=10GB
%nproc=20
#p B3LYP/def2svp TD(singlet,nstates=10,root=2) opt freq em=gd3bj

S2 TDDFT opt+freq

0 1
C 0.0 0.0 0.0
H 0.0 0.0 1.0

"""

_NACME = """%chk=x.chk
%mem=10GB
%nproc=28
#p td B3LYP/def2svp em=gd3bj prop=field iop(6/22=-4, 6/29=1, 6/30=0, 6/17=2) nosymm

NACME

0 1
C 0.0 0.0 0.0

"""


def _write_tmp(text: str, tmp_path: Path) -> Path:
    p = tmp_path / "in.com"
    p.write_text(text)
    return p


def test_parse_opt_freq(tmp_path: Path):
    from chemaster.mcp.calc_gaussian.server import parse_input
    r = parse_input(str(_write_tmp(_OPT_FREQ, tmp_path)))
    assert r["ok"]
    res = r["result"]
    assert res["task"] == "opt_freq"
    assert res["method"].lower() == "b3lyp"
    assert res["basis"] == "def2-SVP"
    assert res["charge"] == 0 and res["multiplicity"] == 1
    assert res["n_atoms"] == 3
    assert res["has_dispersion"]
    # Workflow mapping should include both optimize and frequency
    tools = [w["tool"] for w in res["suggested_chemmaster_workflow"]]
    assert "calc_psi4_optimize" in tools
    assert "calc_psi4_frequency" in tools


def test_parse_td_singlet_opt_freq(tmp_path: Path):
    from chemaster.mcp.calc_gaussian.server import parse_input
    r = parse_input(str(_write_tmp(_TD_OPT_FREQ_SINGLET, tmp_path)))
    assert r["ok"]
    res = r["result"]
    assert res["task"] == "td_opt_freq"
    assert res["has_td"]
    assert not res["is_triplet_td"]
    assert res["link0"]["mem"] == "10GB"
    assert res["link0"]["nproc"] == "20"


def test_parse_nacme(tmp_path: Path):
    from chemaster.mcp.calc_gaussian.server import parse_input
    r = parse_input(str(_write_tmp(_NACME, tmp_path)))
    assert r["ok"]
    res = r["result"]
    assert res["task"] == "nacme"
    assert res["has_nacme"]


def test_parse_nonexistent_file_returns_error():
    from chemaster.mcp.calc_gaussian.server import parse_input
    r = parse_input("/no/such/file.com")
    assert not r["ok"]
    assert r["error_code"] == "FILE_NOT_FOUND"


def test_run_engine_not_found(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(shutil, "which", lambda _x: None)
    from chemaster.mcp.calc_gaussian.server import run
    p = tmp_path / "x.com"
    p.write_text(_OPT_FREQ)
    r = run(str(p))
    assert not r["ok"]
    assert r["error_code"] == "ENGINE_NOT_FOUND"
    assert "psi4" in r["suggestion"].lower() or "orca" in r["suggestion"].lower()


def test_calc_gaussian_tools_registered():
    from chemaster.agent.tool_loader import build_default_registry
    reg = build_default_registry()
    assert reg.has("gaussian_parse_input")
    assert reg.has("gaussian_run")


# ──────────────────────────────────────────────────────────────────────────
# Real師姐 benchmark file (skip if not present in worktree)
# ──────────────────────────────────────────────────────────────────────────


_JINGTI_DIR = Path("benchmarks/momap-jingti/raw")


@pytest.mark.skipif(not _JINGTI_DIR.is_dir(),
                    reason="momap-jingti raw files not present in worktree")
def test_parses_real_jingti_inputs():
    """The 5师姐 .com files all parse cleanly with sensible tasks."""
    from chemaster.mcp.calc_gaussian.server import parse_input

    files = list(_JINGTI_DIR.glob("*.com"))
    assert files, "no .com files present"
    parsed: dict[str, str] = {}
    for f in files:
        r = parse_input(str(f))
        assert r["ok"], f"{f}: {r}"
        res = r["result"]
        parsed[f.name] = res["task"]
        # All five inputs are at B3LYP/def2-SVP with D3BJ
        assert res["method"].lower() == "b3lyp"
        assert "def2" in res["basis"].lower()
        assert res["has_dispersion"]
        assert res["formula"] == "C24F8H8I4N2"
        assert res["n_atoms"] == 46

    # Spot-check the tasks
    assert parsed.get("jingti-00TDopt2(1).com") == "td_opt_freq"
    assert parsed.get("Tjingti-00TDopt1(1).com") == "td_opt_freq"
    assert parsed.get("jingti-00optnacmes1(1).com") == "nacme"
    assert parsed.get("jingti-00optnacmes2(1).com") == "nacme"
