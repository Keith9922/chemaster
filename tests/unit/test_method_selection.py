"""Unit tests for ``chemaster.kb.method_selection`` — the rule engine."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


# ──────────────────────────────────────────────────────────────────────────────
# Built-in ruleset — verify it parses + the headline rules exist
# ──────────────────────────────────────────────────────────────────────────────

class TestBuiltinRulesetWellFormed:
    def test_yaml_parses(self):
        from chemaster.kb.method_selection import _builtin_path
        data = yaml.safe_load(_builtin_path().read_text())
        assert isinstance(data, dict)
        assert "rules" in data
        assert isinstance(data["rules"], list)
        assert len(data["rules"]) > 5

    def test_every_rule_has_required_fields(self):
        from chemaster.kb.method_selection import _builtin_path
        data = yaml.safe_load(_builtin_path().read_text())
        ids = set()
        for r in data["rules"]:
            assert "id" in r, r
            assert "rationale" in r, r
            assert "when" in r, r
            assert "recommend" in r, r
            assert r["id"] not in ids, f"duplicate id {r['id']!r}"
            ids.add(r["id"])

    def test_fallback_rule_present(self):
        """The 'fallback_any' rule must always exist — without it,
        select_method() can return None and the agent has nowhere to land."""
        from chemaster.kb.method_selection import load_rules
        ids = {r.id for r in load_rules()}
        assert "fallback_any" in ids


# ──────────────────────────────────────────────────────────────────────────────
# Rule.matches() — condition semantics
# ──────────────────────────────────────────────────────────────────────────────

class TestRuleMatching:
    def _rule(self, when: dict):
        from chemaster.kb.method_selection import MethodRule
        return MethodRule(id="x", priority=10, when=when, recommend={"method": "X"})

    def test_empty_when_matches_everything(self):
        r = self._rule({})
        assert r.matches({}) is True
        assert r.matches({"task_type": "anything"}) is True

    def test_single_value_must_match_exactly(self):
        r = self._rule({"task_type": "optimize"})
        assert r.matches({"task_type": "optimize"}) is True
        assert r.matches({"task_type": "single_point"}) is False

    def test_pipe_alternation(self):
        r = self._rule({"task_type": "optimize|frequency|tddft"})
        for t in ("optimize", "frequency", "tddft"):
            assert r.matches({"task_type": t}) is True
        assert r.matches({"task_type": "soc"}) is False

    def test_any_passes_anything(self):
        r = self._rule({"task_type": "any"})
        assert r.matches({"task_type": "optimize"}) is True
        # Missing key still passes because the rule wildcards it.
        assert r.matches({}) is True

    def test_missing_query_key_with_specific_rule_fails(self):
        """If the rule demands a specific task_type but the query omits it,
        the rule must NOT match — otherwise overly-broad fallbacks would
        win when the chemist hasn't classified the task yet."""
        r = self._rule({"task_type": "optimize"})
        assert r.matches({}) is False

    def test_multiple_conditions_all_must_pass(self):
        r = self._rule({
            "task_type": "optimize",
            "molecule_class": "small_organic",
        })
        assert r.matches({"task_type": "optimize",
                          "molecule_class": "small_organic"}) is True
        assert r.matches({"task_type": "optimize",
                          "molecule_class": "radical"}) is False


# ──────────────────────────────────────────────────────────────────────────────
# select_method() — full pipeline
# ──────────────────────────────────────────────────────────────────────────────

class TestSelectMethod:
    def test_small_org_default(self):
        from chemaster.kb.method_selection import select_method
        r = select_method(task_type="single_point",
                          molecule_class="small_organic",
                          size="small")
        assert r is not None
        assert r["rule_id"] == "small_org_ground_state"
        assert r["method"] == "B3LYP-D3(BJ)"
        assert r["basis"] == "def2-TZVP"
        assert r["backend"] == "psi4"

    def test_radical_overrides_small_org(self):
        from chemaster.kb.method_selection import select_method
        r = select_method(task_type="single_point",
                          molecule_class="radical",
                          size="small")
        # 'open_shell_radical' has priority 90 > 'small_org_ground_state' (50)
        assert r["rule_id"] == "open_shell_radical"
        assert r.get("reference") == "uhf"

    def test_tddft_singlet_returns_cam_b3lyp(self):
        from chemaster.kb.method_selection import select_method
        r = select_method(task_type="tddft",
                          excitation_character="singlet")
        assert r["rule_id"] == "tddft_singlet"
        assert r["method"] == "CAM-B3LYP"
        assert r["tda"] is True

    def test_rydberg_overrides_singlet(self):
        from chemaster.kb.method_selection import select_method
        r = select_method(task_type="tddft",
                          excitation_character="rydberg")
        assert r["rule_id"] == "tddft_rydberg"
        # The diffuse-functions point
        assert "aug-cc" in r["basis"]

    def test_soc_routes_to_bdf(self):
        from chemaster.kb.method_selection import select_method
        r = select_method(task_type="soc")
        assert r["rule_id"] == "soc_relativistic"
        assert r["backend"] == "bdf"

    def test_unknown_task_falls_back(self):
        from chemaster.kb.method_selection import select_method
        r = select_method(task_type="totally_made_up_task")
        # fallback_any.when.task_type is "any" so it always matches.
        assert r is not None
        assert r["rule_id"] == "fallback_any"

    def test_no_task_type_still_returns_fallback(self):
        from chemaster.kb.method_selection import select_method
        r = select_method()
        assert r is not None
        assert r["rule_id"] == "fallback_any"


# ──────────────────────────────────────────────────────────────────────────────
# User override — write a YAML to a tmp user_kb dir and verify merge
# ──────────────────────────────────────────────────────────────────────────────

class TestUserOverride:
    @pytest.fixture
    def patched_user_kb(self, monkeypatch, tmp_path):
        """Point chemaster.agent.user_kb at tmp_path so the test can write
        a user method_selection.yaml without touching the real ~/.chemaster."""
        monkeypatch.setenv("CHEMASTER_USER_KB_DIR", str(tmp_path))
        return tmp_path

    def test_user_can_add_new_rule(self, patched_user_kb):
        rules_dir = patched_user_kb / "rules"
        rules_dir.mkdir(parents=True, exist_ok=True)
        (rules_dir / "method_selection.yaml").write_text(
            yaml.safe_dump({"rules": [{
                "id": "my_custom_rule",
                "priority": 200,
                "when": {"task_type": "my_special_task"},
                "recommend": {"method": "CCSD(T)", "basis": "cc-pVDZ",
                              "backend": "psi4"},
                "rationale": "user-added rule",
            }]})
        )
        from chemaster.kb.method_selection import select_method, load_rules
        # The new rule is loaded.
        ids = {r.id for r in load_rules()}
        assert "my_custom_rule" in ids
        # And it routes correctly.
        r = select_method(task_type="my_special_task")
        assert r["rule_id"] == "my_custom_rule"
        assert r["source"] == "user"
        assert r["method"] == "CCSD(T)"

    def test_user_can_override_builtin_by_id(self, patched_user_kb):
        rules_dir = patched_user_kb / "rules"
        rules_dir.mkdir(parents=True, exist_ok=True)
        # Override small_org_ground_state to prefer ωB97X-D instead
        (rules_dir / "method_selection.yaml").write_text(
            yaml.safe_dump({"rules": [{
                "id": "small_org_ground_state",
                "priority": 50,
                "when": {"task_type": "single_point|optimize|frequency",
                          "molecule_class": "small_organic",
                          "size": "very_small|small|medium"},
                "recommend": {"method": "wB97X-D", "basis": "def2-TZVP",
                              "backend": "psi4"},
                "rationale": "Lab preference: ωB97X-D for ground-state energetics.",
            }]})
        )
        from chemaster.kb.method_selection import select_method, load_rules
        # Only one rule with that id should exist post-merge.
        with_id = [r for r in load_rules() if r.id == "small_org_ground_state"]
        assert len(with_id) == 1
        assert with_id[0].source == "user"

        # And select_method now returns the user's choice
        r = select_method(task_type="single_point",
                          molecule_class="small_organic",
                          size="small")
        assert r["method"] == "wB97X-D"
        assert r["source"] == "user"
        assert "Lab preference" in r["rationale"]

    def test_user_rule_picks_higher_priority(self, patched_user_kb):
        """Two rules match — the higher-priority user rule wins even if
        it has a different id from any built-in."""
        rules_dir = patched_user_kb / "rules"
        rules_dir.mkdir(parents=True, exist_ok=True)
        (rules_dir / "method_selection.yaml").write_text(
            yaml.safe_dump({"rules": [{
                "id": "lab_specific_org_default",
                "priority": 100,   # > small_org_ground_state.priority of 50
                "when": {"task_type": "single_point",
                          "molecule_class": "small_organic"},
                "recommend": {"method": "PBE0-D3(BJ)", "basis": "def2-TZVP",
                              "backend": "psi4"},
                "rationale": "Our group standardised on PBE0-D3 in 2024.",
            }]})
        )
        from chemaster.kb.method_selection import select_method
        r = select_method(task_type="single_point",
                          molecule_class="small_organic",
                          size="small")
        assert r["rule_id"] == "lab_specific_org_default"
        assert r["method"] == "PBE0-D3(BJ)"


# ──────────────────────────────────────────────────────────────────────────────
# Listing UI helper
# ──────────────────────────────────────────────────────────────────────────────

class TestAllRulesForListing:
    def test_returns_sorted_by_priority(self):
        from chemaster.kb.method_selection import all_rules_for_listing
        rules = all_rules_for_listing()
        priorities = [r["priority"] for r in rules]
        assert priorities == sorted(priorities, reverse=True)

    def test_source_field_set(self):
        from chemaster.kb.method_selection import all_rules_for_listing
        for r in all_rules_for_listing():
            assert r["source"] in ("builtin", "user")
