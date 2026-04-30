"""calc_bdf and analysis_multiwfn — engine-not-found + parser tests.

Neither BDF nor MultiWFN are installed in CI / dev environments by
default. These tests cover the cold path (clean ENGINE_NOT_FOUND with
useful install hints), input-file generation, and output parsing on
fixture text.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest


# ──────────────────────────────────────────────────────────────────────────
# BDF
# ──────────────────────────────────────────────────────────────────────────


def test_bdf_engine_not_found_when_missing(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda _x: None)
    from chemaster.mcp.calc_bdf.server import soc
    r = soc("3\nH2O\nO 0 0 0\nH 1 0 0\nH 0 1 0\n")
    assert not r["ok"]
    assert r["error_code"] == "ENGINE_NOT_FOUND"
    assert "bdf-manual" in r["suggestion"].lower() or "bdf" in r["suggestion"].lower()


def test_bdf_no_bdfhome_when_binary_present(monkeypatch):
    monkeypatch.setattr(shutil, "which",
                        lambda x: "/fake/bin/bdf" if x in ("bdf", "bdfdrv.py") else None)
    monkeypatch.setattr(
        "chemaster.mcp.calc_bdf.server.subprocess.run",
        lambda *a, **kw: type("X", (), {"stdout": "BDF Version 1.0", "stderr": ""})(),
    )
    monkeypatch.delenv("BDFHOME", raising=False)
    from chemaster.mcp.calc_bdf.server import soc
    r = soc("3\nH2O\nO 0 0 0\nH 1 0 0\nH 0 1 0\n")
    assert not r["ok"]
    assert r["error_code"] == "NO_BDFHOME"


def test_bdf_xyz_to_geom_block_uses_2s_not_2sp1():
    """BDF Spin field is 2S, not multiplicity (2S+1)."""
    from chemaster.mcp.calc_bdf.server import _xyz_to_bdf_geom
    block = _xyz_to_bdf_geom(
        "1\nH atom\nH 0 0 0\n", charge=0, multiplicity=2,
    )
    assert "$compass" in block
    assert "Spin\n1" in block            # multiplicity 2 → 2S = 1
    assert "Charge\n0" in block


def test_bdf_soc_parser_reads_matrix_elements():
    from chemaster.mcp.calc_bdf.server import _parse_soc
    sample = """
    SOC matrix element  1 - 1     12.5 cm-1
    SOC matrix element  1 - 2     8.32 cm-1
    Some other text
    SOC matrix element  2 - 1     8.32 cm-1
    """
    out = _parse_soc(sample)
    assert len(out["soc_elements"]) == 3
    assert out["soc_elements"][0]["matrix_element"]["unit"] == "cm^-1"


def test_bdf_tool_registered():
    from chemaster.agent.tool_loader import build_default_registry
    reg = build_default_registry()
    assert reg.has("calc_bdf_soc")


# ──────────────────────────────────────────────────────────────────────────
# MultiWFN
# ──────────────────────────────────────────────────────────────────────────


def test_multiwfn_engine_not_found_when_missing(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda _x: None)
    from chemaster.mcp.analysis_multiwfn.server import nto_analysis
    r = nto_analysis("/tmp/nope.molden")
    assert not r["ok"]
    assert r["error_code"] == "ENGINE_NOT_FOUND"
    assert "multiwfn" in r["suggestion"].lower()


def test_multiwfn_file_not_found_when_path_missing(monkeypatch):
    """If the binary exists but the wavefunction file doesn't, surface a
    distinct error."""
    monkeypatch.setattr(
        shutil, "which",
        lambda x: "/fake/bin/Multiwfn" if x in ("Multiwfn", "multiwfn") else None,
    )
    from chemaster.mcp.analysis_multiwfn.server import nto_analysis
    r = nto_analysis("/this/file/does/not/exist.molden")
    assert not r["ok"]
    assert r["error_code"] == "FILE_NOT_FOUND"


def test_multiwfn_nto_parser_reads_pairs():
    from chemaster.mcp.analysis_multiwfn.server import _parse_nto
    sample = """
       Pair    Hole occ.   Particle  Particle occ.    Weight
        1       0.4500       2          0.4500          0.4521
        2       0.3200       3          0.3200          0.3245
        3       0.0500       4          0.0500          0.0500
    """
    out = _parse_nto(sample)
    assert len(out["nto_pairs"]) == 3
    p = out["nto_pairs"][0]
    assert p["pair_index"] == 1
    assert p["weight"] == pytest.approx(0.4521)


def test_multiwfn_tool_registered():
    from chemaster.agent.tool_loader import build_default_registry
    reg = build_default_registry()
    assert reg.has("analysis_nto")
