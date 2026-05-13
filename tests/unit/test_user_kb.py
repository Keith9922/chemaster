"""Unit tests for the user-KB mechanism."""
from __future__ import annotations

import os
from pathlib import Path
from textwrap import dedent

import pytest
import yaml

from chemaster.agent import user_kb
from chemaster.mcp.kb import server as kb_server


@pytest.fixture
def isolated_user_kb(tmp_path, monkeypatch):
    """Redirect CHEMASTER_USER_KB_DIR to a tmp directory and reset KB cache."""
    monkeypatch.setenv("CHEMASTER_USER_KB_DIR", str(tmp_path))
    kb_server.reset_doc_cache()
    yield tmp_path
    kb_server.reset_doc_cache()


# ── path resolution ─────────────────────────────────────────────────────────


def test_user_kb_root_respects_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("CHEMASTER_USER_KB_DIR", str(tmp_path / "my_kb"))
    assert user_kb.user_kb_root() == tmp_path / "my_kb"


def test_user_kb_root_respects_chemaster_home(tmp_path, monkeypatch):
    monkeypatch.delenv("CHEMASTER_USER_KB_DIR", raising=False)
    monkeypatch.setenv("CHEMASTER_HOME", str(tmp_path / "ch"))
    assert user_kb.user_kb_root() == tmp_path / "ch" / "user_kb"


def test_user_kb_root_default(monkeypatch):
    monkeypatch.delenv("CHEMASTER_USER_KB_DIR", raising=False)
    monkeypatch.delenv("CHEMASTER_HOME", raising=False)
    assert user_kb.user_kb_root() == Path.home() / ".chemaster" / "user_kb"


def test_ensure_layout_idempotent(isolated_user_kb):
    user_kb.ensure_user_kb_layout()
    user_kb.ensure_user_kb_layout()  # should not raise
    for sub in ("rules", "skills", "notes"):
        assert (isolated_user_kb / sub).is_dir()


# ── preferences ─────────────────────────────────────────────────────────────


def test_prefs_missing_returns_empty(isolated_user_kb):
    prefs = user_kb.load_user_prefs()
    assert prefs.raw == {}
    assert prefs.categories == {}
    assert prefs.notes == []
    assert prefs.as_system_prompt_snippet() == ""


def test_prefs_categories_and_notes(isolated_user_kb):
    user_kb.ensure_user_kb_layout()
    user_kb.user_kb_prefs_path().write_text(dedent("""
        ground_state_dft: Gaussian
        soc: BDF
        tvcf_rate: MOMAP
        default_functional: B3LYP-D3(BJ)
        unknown_field: should_be_ignored_in_categories
        notes:
          - "Always use ωB97X-D for CT states."
          - "Prefer def2-TZVP for routine work."
    """))
    prefs = user_kb.load_user_prefs()
    cats = prefs.categories
    assert cats["ground_state_dft"] == "Gaussian"
    assert cats["soc"] == "BDF"
    assert cats["tvcf_rate"] == "MOMAP"
    assert "unknown_field" not in cats
    assert len(prefs.notes) == 2

    snippet = prefs.as_system_prompt_snippet()
    assert "Gaussian" in snippet
    assert "BDF" in snippet
    assert "ωB97X-D" in snippet
    assert "recommend" in snippet.lower()


def test_prefs_get_with_synonyms(isolated_user_kb):
    user_kb.ensure_user_kb_layout()
    user_kb.user_kb_prefs_path().write_text(dedent("""
        soc: BDF
        tvcf_rate: MOMAP
    """))
    prefs = user_kb.load_user_prefs()
    assert prefs.get("soc") == "BDF"
    assert prefs.get("relativistic") == "BDF"      # synonym
    assert prefs.get("spectroscopy") == "MOMAP"    # synonym
    assert prefs.get("phosphorescence") == "MOMAP" # synonym
    assert prefs.get("unknown_task", default="psi4") == "psi4"


def test_prefs_malformed_yaml_ignored(isolated_user_kb):
    user_kb.ensure_user_kb_layout()
    user_kb.user_kb_prefs_path().write_text("not: valid: yaml: : :")
    prefs = user_kb.load_user_prefs()
    assert prefs.raw == {}


def test_save_prefs_roundtrip(isolated_user_kb):
    prefs = user_kb.UserPreferences(raw={"soc": "BDF", "notes": ["hi"]})
    path = user_kb.save_user_prefs(prefs)
    assert path.exists()
    reloaded = user_kb.load_user_prefs()
    assert reloaded.raw["soc"] == "BDF"
    assert reloaded.notes == ["hi"]


# ── adding / listing / removing docs ─────────────────────────────────────────


def test_add_yaml_auto_routes_to_rules(isolated_user_kb, tmp_path):
    src = tmp_path / "my_custom.yaml"
    src.write_text(yaml.safe_dump({
        "custom_functionals": [
            {"name": "MY-DFT", "note": "house functional"}
        ]
    }))
    dest = user_kb.add_user_doc(src)
    assert dest.parent.name == "rules"
    assert dest.name == "my_custom.yaml"
    assert dest.exists()


def test_add_skill_explicit_kind(isolated_user_kb, tmp_path):
    src = tmp_path / "my_pipeline.md"
    src.write_text("# Custom Skill\n\nHow to do my thing.\n")
    dest = user_kb.add_user_doc(src, kind="skill")
    assert dest.name == "SKILL.md"
    assert dest.parent.name == "my_pipeline"
    assert dest.parent.parent.name == "skills"


def test_add_note_md(isolated_user_kb, tmp_path):
    src = tmp_path / "memo.md"
    src.write_text("Random memo.")
    dest = user_kb.add_user_doc(src, kind="notes")
    assert dest.parent.name == "notes"
    assert dest.suffix == ".md"


def test_add_missing_source_raises(isolated_user_kb, tmp_path):
    with pytest.raises(FileNotFoundError):
        user_kb.add_user_doc(tmp_path / "nope.yaml")


def test_add_unknown_extension_requires_explicit_kind(isolated_user_kb, tmp_path):
    src = tmp_path / "foo.txt"
    src.write_text("hello")
    with pytest.raises(ValueError):
        user_kb.add_user_doc(src)


def test_list_user_docs_after_add(isolated_user_kb, tmp_path):
    yaml_src = tmp_path / "rules1.yaml"
    yaml_src.write_text("x: []")
    skill_src = tmp_path / "skill_x.md"
    skill_src.write_text("# skill x")
    user_kb.add_user_doc(yaml_src)
    user_kb.add_user_doc(skill_src, kind="skill", dest_name="skill_x")
    listing = user_kb.list_user_docs()
    assert "rules1.yaml" in listing["rules"]
    assert "skill_x" in listing["skills"]


def test_remove_user_doc(isolated_user_kb, tmp_path):
    src = tmp_path / "to_remove.yaml"
    src.write_text("a: []")
    user_kb.add_user_doc(src)
    assert user_kb.remove_user_doc("rules", "to_remove") is True
    assert user_kb.remove_user_doc("rules", "nonexistent") is False


# ── integration with kb.server ──────────────────────────────────────────────


def test_kb_search_picks_up_user_skill(isolated_user_kb, tmp_path):
    user_kb.ensure_user_kb_layout()
    skill_dir = isolated_user_kb / "skills" / "yhk_special_emitter"
    skill_dir.mkdir(parents=True)
    # Use deliberately rare strings so the user skill outranks built-in docs.
    (skill_dir / "SKILL.md").write_text(dedent("""\
        # YHK-special emitter family

        For our YHK74-family OLED emitters use:
        - functional: omegaB97X-D
        - basis: def2-TZVP
        - rare-keyword: zynobotron-protocol
        Reorganisation should be analysed with rare-keyword wave-foo.
    """))
    kb_server.reset_doc_cache()
    from chemaster.mcp.kb.server import kb_search

    # Query a rare term that only exists in the user skill, so the user doc
    # must be the top hit if loading works.
    result = kb_search(query="YHK74 zynobotron wave-foo", top_k=5)
    assert result["ok"] is True
    hits = result["result"]["hits"]
    assert hits, "expected at least one hit for the rare query"
    top = hits[0]
    assert top["doc_id"].startswith("user_kb/skills/yhk_special_emitter"), (
        f"User-provided skill should be the top hit, got: "
        f"{[h['doc_id'] for h in hits]}"
    )
    assert top["kind"] == "skill"


def test_kb_search_picks_up_user_rule(isolated_user_kb):
    user_kb.ensure_user_kb_layout()
    (isolated_user_kb / "rules" / "custom_emitter_targets.yaml").write_text(dedent("""
        targets:
          - name: my_target_molecule
            description: "BODIPY-core green emitter for OLED"
            preferred_method: "ωB97X-D / def2-TZVP"
    """))
    kb_server.reset_doc_cache()
    from chemaster.mcp.kb.server import kb_search

    result = kb_search(query="BODIPY OLED emitter ωB97X-D", top_k=3)
    assert result["ok"] is True
    hits = result["result"]["hits"]
    assert any("user_kb" in h["doc_id"] for h in hits)


def test_kb_search_user_docs_dont_break_existing_search(isolated_user_kb):
    """Built-in docs still searchable even when user KB is empty layout."""
    user_kb.ensure_user_kb_layout()  # creates dirs but no docs
    kb_server.reset_doc_cache()
    from chemaster.mcp.kb.server import kb_search

    result = kb_search(query="TADF kRISC", top_k=3)
    assert result["ok"] is True
    assert len(result["result"]["hits"]) > 0
