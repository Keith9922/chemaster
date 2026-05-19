"""Method-selection rule engine.

Loads ``chemaster/kb/rules/method_selection.yaml`` (the built-in defaults)
and merges any user overrides from
``~/.chemaster/user_kb/rules/method_selection.yaml``. Exposes a single
:func:`select_method` query function that the agent (and the L2 recommend
path) uses when picking method/basis/backend for a chemistry task.

Why a separate module?
  - Keeps the YAML schema in one place (``method_selection.yaml``) instead
    of scattered ``if intent.contains(...)`` branches in agent code.
  - Makes the policy declarative and *user-overridable* without code edits.
  - Lets the agent surface the matched ``rule_id`` and ``rationale`` in
    every recommend card so the chemist sees which rule fired.

Concept summary:
  rules ::= [ rule ]
  rule  ::= { id, priority, when: {field: glob}, recommend: {…}, rationale }

  match(rule, query): every field in `rule["when"]` must match the
  corresponding field in `query`. A rule field of "any" matches anything;
  pipe-separated alternatives ("optimize|frequency") match if any token
  equals the query value. Missing query fields are treated as "any".

  select_method(query): returns the highest-priority matching rule,
  ties broken by user-rules > built-in.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from chemaster.agent.user_kb import user_kb_subdir

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Data classes
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class MethodRule:
    """One method-selection rule, parsed from YAML."""
    id: str
    priority: int
    when: dict[str, str] = field(default_factory=dict)
    recommend: dict[str, Any] = field(default_factory=dict)
    rationale: str = ""
    source: str = "builtin"      # "builtin" | "user"
    source_path: str | None = None  # filesystem path for traceability

    def matches(self, query: dict[str, Any]) -> bool:
        """Return True if every condition in ``self.when`` matches ``query``.

        Each condition value is either:
          - the string ``"any"`` (matches anything)
          - a single value (must equal the query's value)
          - a pipe-separated list ``"a|b|c"`` (matches if query value is in
            {a, b, c})

        Missing keys in ``query`` are treated as the wildcard "any", so a
        rule with ``when: { task_type: optimize }`` against a query that
        omits ``task_type`` does NOT match.
        """
        for key, condition in self.when.items():
            if condition == "any":
                continue
            q = query.get(key)
            if q is None:
                return False
            allowed = condition.split("|") if isinstance(condition, str) else [condition]
            allowed = [a.strip() for a in allowed]
            # "any" within an alternation also passes
            if "any" in allowed:
                continue
            if str(q) not in allowed:
                return False
        return True


# ──────────────────────────────────────────────────────────────────────────────
# Loading
# ──────────────────────────────────────────────────────────────────────────────

def _builtin_path() -> Path:
    """Path to the built-in YAML — next to this module."""
    return Path(__file__).resolve().parent / "rules" / "method_selection.yaml"


def _user_path() -> Path:
    """Path to the user override (always under ``user_kb_subdir``)."""
    return user_kb_subdir("rules", create=False) / "method_selection.yaml"


def _parse_rules(path: Path, source_label: str) -> list[MethodRule]:
    """Parse a YAML file into a list of :class:`MethodRule` objects."""
    if not path.exists():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        logger.warning("Failed to parse %s: %s", path, exc)
        return []
    if not isinstance(data, dict) or "rules" not in data:
        logger.warning("%s has no 'rules' key — ignoring", path)
        return []
    out: list[MethodRule] = []
    for i, raw in enumerate(data["rules"] or []):
        if not isinstance(raw, dict):
            logger.warning("%s: rule %d is not a mapping — skipping", path, i)
            continue
        try:
            rule = MethodRule(
                id=str(raw["id"]),
                priority=int(raw.get("priority", 0)),
                when=dict(raw.get("when") or {}),
                recommend=dict(raw.get("recommend") or {}),
                rationale=str(raw.get("rationale", "")),
                source=source_label,
                source_path=str(path),
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("%s: rule %d invalid (%s) — skipping", path, i, exc)
            continue
        out.append(rule)
    return out


def load_rules() -> list[MethodRule]:
    """Load built-in + user rules, with user winning on id collision.

    Returns the merged ruleset sorted by descending priority. Suitable for
    direct use by :func:`select_method`; callers that want the raw rule
    objects (e.g. to render a UI) can use this too.
    """
    builtin = _parse_rules(_builtin_path(), "builtin")
    user = _parse_rules(_user_path(), "user")

    # User rules override built-ins by id; otherwise both coexist.
    by_id: dict[str, MethodRule] = {r.id: r for r in builtin}
    for r in user:
        if r.id in by_id:
            logger.info("User rule %r overrides built-in.", r.id)
        by_id[r.id] = r

    merged = list(by_id.values())
    merged.sort(key=lambda r: r.priority, reverse=True)
    return merged


# ──────────────────────────────────────────────────────────────────────────────
# Query API
# ──────────────────────────────────────────────────────────────────────────────

def select_method(
    task_type: str | None = None,
    *,
    molecule_class: str | None = None,
    contains_element: str | None = None,
    size: str | None = None,
    excitation_character: str | None = None,
    accuracy_required: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Pick the best-matching rule for a chemistry task.

    Returns the matched rule as a dict::

        {
            "rule_id":   "small_org_ground_state",
            "source":    "builtin",
            "priority":  50,
            "method":    "B3LYP-D3(BJ)",
            "basis":     "def2-TZVP",
            "backend":   "psi4",
            "rationale": "...",
            ...
        }

    Returns ``None`` if no rule matches (which should not happen if the
    built-in ``fallback_any`` rule is intact).

    All arguments are optional; only the keys you pass are matched. The
    `extra` dict can carry additional conditions (e.g. ``{"reference":
    "uhf"}``) for user-defined rule extensions.
    """
    query: dict[str, Any] = {}
    if task_type is not None:
        query["task_type"] = task_type
    if molecule_class is not None:
        query["molecule_class"] = molecule_class
    if contains_element is not None:
        query["contains_element"] = contains_element
    if size is not None:
        query["size"] = size
    if excitation_character is not None:
        query["excitation_character"] = excitation_character
    if accuracy_required is not None:
        query["accuracy_required"] = accuracy_required
    if extra:
        query.update(extra)

    for rule in load_rules():  # already sorted by priority desc
        if rule.matches(query):
            out: dict[str, Any] = {
                "rule_id": rule.id,
                "source": rule.source,
                "source_path": rule.source_path,
                "priority": rule.priority,
                "rationale": rule.rationale,
            }
            out.update(rule.recommend)
            return out
    return None


def all_rules_for_listing() -> list[dict[str, Any]]:
    """Render the merged ruleset as a list of dicts (for `chemaster kb
    method-rules` and similar UI views)."""
    out = []
    for r in load_rules():
        out.append({
            "id": r.id,
            "priority": r.priority,
            "source": r.source,
            "source_path": r.source_path,
            "when": dict(r.when),
            "recommend": dict(r.recommend),
            "rationale": r.rationale,
        })
    return out
