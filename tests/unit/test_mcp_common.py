"""chemaster/mcp/_common.py 公共骨架测试。"""

from __future__ import annotations

import pytest

from chemaster.mcp._common import err, ok, probe_binary, xyz_atom_lines

# ── envelope ─────────────────────────────────────────────────────────────────


def test_ok_shape():
    r = ok({"e": -1.17}, warnings=["w"], meta={"m": 1}, data_source="real")
    assert r["ok"] is True
    assert r["result"] == {"e": -1.17}
    assert r["warnings"] == ["w"]
    assert r["meta"] == {"m": 1}
    assert r["data_source"] == "real"


def test_err_requires_suggestion():
    r = err("TIMEOUT", "took too long", "increase timeout_s")
    assert r["ok"] is False and r["error_code"] == "TIMEOUT"
    assert r["suggestion"] == "increase timeout_s"
    with pytest.raises(ValueError):
        err("TIMEOUT", "took too long", "")


# ── probe_binary ─────────────────────────────────────────────────────────────


def test_probe_binary_missing(monkeypatch):
    import chemaster.mcp._common as C
    monkeypatch.setattr(C.shutil, "which", lambda _x: None)
    assert probe_binary(("nonexistent-engine",)) == (None, "")


def test_probe_binary_found_no_version_probe(monkeypatch):
    import chemaster.mcp._common as C
    monkeypatch.setattr(C.shutil, "which",
                        lambda x: "/usr/bin/" + x if x == "g16" else None)
    path, ver = probe_binary(("g16", "g09"))
    assert path == "/usr/bin/g16" and ver == "unknown"


def test_probe_binary_version_regex(monkeypatch):
    import chemaster.mcp._common as C
    monkeypatch.setattr(C.shutil, "which", lambda x: "/opt/orca")

    class P:
        stdout = "Program Version 5.0.4 - RELEASE"
        stderr = ""

    monkeypatch.setattr(C.subprocess, "run", lambda *a, **kw: P())
    path, ver = probe_binary(("orca",), version_args=[],
                             version_regex=r"Program Version\s+(\S+)")
    assert ver == "5.0.4"


def test_probe_binary_version_crash_still_reports_path(monkeypatch):
    import chemaster.mcp._common as C
    monkeypatch.setattr(C.shutil, "which", lambda x: "/opt/bdf")

    def boom(*a, **kw):
        raise OSError("exec format error")

    monkeypatch.setattr(C.subprocess, "run", boom)
    path, ver = probe_binary(("bdf",), version_args=["--version"])
    assert path == "/opt/bdf" and ver == "unknown"


# ── xyz_atom_lines ───────────────────────────────────────────────────────────


def test_xyz_standard_with_comment():
    atoms = xyz_atom_lines("2\nhydrogen\nH 0 0 0\nH 0 0 0.74\n")
    assert atoms == ["H 0 0 0", "H 0 0 0.74"]


def test_xyz_no_comment_line():
    atoms = xyz_atom_lines("2\nH 0 0 0\nH 0 0 0.74")
    assert len(atoms) == 2


def test_xyz_bare_atom_lines():
    atoms = xyz_atom_lines("O 0 0 0\nH 0 0 1\nH 0 1 0")
    assert len(atoms) == 3 and atoms[0].startswith("O")


def test_xyz_rejects_empty_and_truncated():
    with pytest.raises(ValueError):
        xyz_atom_lines("   ")
    with pytest.raises(ValueError):
        xyz_atom_lines("5\ncomment\nH 0 0 0")


def test_xyz_comment_not_eaten_when_atom_short():
    """回归（审查发现）：声明 3 原子但只给 2 + 注释行时，注释不能被当成
    原子——用内容判据抓出真错误。"""
    with pytest.raises(ValueError, match="declares 3 atoms but 2"):
        xyz_atom_lines("3\nwater\nO 0 0 0\nH 0 0 0.74")


def test_xyz_bare_atom_lines_accepted():
    """回归（真机确认）：真 LLM 常给无 header 的裸原子行，必须接受。"""
    atoms = xyz_atom_lines("H 0 0 0\nH 0 0 0.74")
    assert atoms == ["H 0 0 0", "H 0 0 0.74"]
