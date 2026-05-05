"""Permission policy — v3.0 labor-saving collaborator design.

Loads ``~/.chemaster/policy.yaml`` (or the path in ``CHEMASTER_POLICY``)
to decide which agent decisions are L1 / L2 / L3.

L1 (autonomous): agent silently executes; trajectory tagged
                 ``decision_authority="agent"``.
L2 (recommend):  agent must call ``recommend`` first; user accepts / modifies /
                 cancels. Trajectory tagged ``decision_authority="user-chemistry"``.
L3 (ask_user):   agent must escalate via ``ask_user``; no defaults assumed.
                 Trajectory tagged ``decision_authority="user-chemistry"`` (with
                 ``escalation=true``).

Default policy is shipped with the package and copied to the user's home
directory on first run. Users may edit the file to demote / promote individual
decisions to fit their workflow.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


DEFAULT_POLICY_FILENAME = "policy.yaml"


# ══════════════════════════════════════════════════════════════════════════════
# Default policy (used when no user file exists; also serves as the seed when
# we drop the file into ~/.chemaster/ on first run).
# ══════════════════════════════════════════════════════════════════════════════


DEFAULT_POLICY_TEXT = """# ChemMaster permission policy (v3.0)
#
# Three permission levels:
#   L1 — agent acts silently
#   L2 — agent recommends, user decides (accept / modify / cancel)
#   L3 — agent must escalate via ask_user (no defaults assumed)
#
# Decision classes correspond to RecommendTool's ``decision_class`` field.
# You may override individual classes here; missing classes inherit ``default``.
#
# To make ChemMaster more autonomous (e.g. for batch screening), demote L2 →
# L1 by setting ``level: L1``. The trajectory still records every decision —
# only the UI prompt is suppressed.

default: L2

decisions:
  # Routine method / basis / functional choices
  method:           L2
  basis:            L2
  functional:       L2
  solvation:        L2

  # Multiplicity is risky to assume for borderline systems; default L3
  multiplicity:     L3

  # Saddle-point vs misconverged minimum is always L3
  ts_or_min:        L3

  # Replacing a method after L1 retries fail — must ask user
  method_substitution:  L3

  # Switching software backend (e.g. Gaussian → ORCA mid-task)
  backend_switch:   L3

  # Catch-all
  other:            L2

# Operations that NEVER prompt (always L1).
# These are pure technical recovery moves with no chemistry impact.
silent_recoveries:
  - "scf_guess_substitution"
  - "scf_damping_increase"
  - "scf_maxiter_increase"
  - "disk_cleanup_retry"
  - "network_retry"
  - "input_syntax_fix"

# Per-tool overrides (rare; takes precedence over decision_class).
tool_overrides: {}
"""


# ══════════════════════════════════════════════════════════════════════════════
# Data
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class Policy:
    default_level: str = "L2"
    decisions: dict[str, str] = field(default_factory=dict)
    silent_recoveries: list[str] = field(default_factory=list)
    tool_overrides: dict[str, str] = field(default_factory=dict)

    def level_for_decision(self, decision_class: str) -> str:
        """Return L1 / L2 / L3 for a recommend's decision_class."""
        return self.decisions.get(decision_class, self.default_level)

    def level_for_tool(self, tool_name: str) -> str | None:
        """Per-tool override, if any."""
        return self.tool_overrides.get(tool_name)

    def is_silent_recovery(self, recovery_action: str) -> bool:
        return recovery_action in set(self.silent_recoveries)


# ══════════════════════════════════════════════════════════════════════════════
# Loading
# ══════════════════════════════════════════════════════════════════════════════


def _policy_path() -> Path:
    env = os.environ.get("CHEMASTER_POLICY")
    if env:
        return Path(env).expanduser()
    home = Path(os.environ.get("CHEMASTER_HOME", "~/.chemaster")).expanduser()
    return home / DEFAULT_POLICY_FILENAME


def _ensure_user_policy(path: Path) -> None:
    """Copy the default policy to ``path`` if it doesn't exist."""
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DEFAULT_POLICY_TEXT, encoding="utf-8")
    logger.info("Wrote default policy to %s", path)


def load_policy(path: Path | None = None) -> Policy:
    """Load the user's policy, falling back to the bundled default."""
    target = path or _policy_path()
    try:
        _ensure_user_policy(target)
    except OSError as exc:
        logger.warning("Could not write default policy to %s: %s", target, exc)

    text = ""
    try:
        text = target.read_text(encoding="utf-8")
    except OSError:
        text = DEFAULT_POLICY_TEXT

    return _parse_policy(text)


def _parse_policy(text: str) -> Policy:
    try:
        import yaml
    except ImportError:
        # Minimal YAML-less fallback: just use defaults.
        logger.warning("PyYAML not available; using built-in defaults")
        return _parse_default()

    try:
        data = yaml.safe_load(text) or {}
    except Exception as exc:
        logger.warning("Failed to parse policy file: %s; using defaults", exc)
        return _parse_default()

    if not isinstance(data, dict):
        return _parse_default()

    return Policy(
        default_level=str(data.get("default", "L2")),
        decisions={k: str(v) for k, v in (data.get("decisions") or {}).items()},
        silent_recoveries=list(data.get("silent_recoveries") or []),
        tool_overrides={k: str(v) for k, v in (data.get("tool_overrides") or {}).items()},
    )


def _parse_default() -> Policy:
    return Policy(
        default_level="L2",
        decisions={
            "method": "L2",
            "basis": "L2",
            "functional": "L2",
            "solvation": "L2",
            "multiplicity": "L3",
            "ts_or_min": "L3",
            "method_substitution": "L3",
            "backend_switch": "L3",
            "other": "L2",
        },
        silent_recoveries=[
            "scf_guess_substitution",
            "scf_damping_increase",
            "scf_maxiter_increase",
            "disk_cleanup_retry",
            "network_retry",
            "input_syntax_fix",
        ],
        tool_overrides={},
    )


# ══════════════════════════════════════════════════════════════════════════════
# Decision authority — used by trajectory tagging
# ══════════════════════════════════════════════════════════════════════════════


# Constants for the trajectory's decision_authority field.
AUTHORITY_AGENT = "agent"
AUTHORITY_USER_BINARY = "user-binary"        # binary y/n confirm path
AUTHORITY_USER_CHEMISTRY = "user-chemistry"  # recommend / ask_user path
AUTHORITY_SYSTEM = "system"                  # framework events (start / end)


def authority_for_event(
    confirmation_mode: str,
    user_responded: bool,
    is_recommend: bool = False,
    is_ask_user: bool = False,
) -> str:
    """Decide the decision_authority tag for one trajectory event.

    Args:
        confirmation_mode: 'silent' / 'confirm' / 'recommend'
        user_responded: did the user actually respond (vs auto-approve)
        is_recommend: was this a `recommend` tool call
        is_ask_user: was this an `ask_user` tool call
    """
    if is_recommend or is_ask_user:
        return AUTHORITY_USER_CHEMISTRY
    if confirmation_mode == "silent":
        return AUTHORITY_AGENT
    if confirmation_mode == "confirm" and user_responded:
        return AUTHORITY_USER_BINARY
    if confirmation_mode == "recommend" and user_responded:
        return AUTHORITY_USER_CHEMISTRY
    return AUTHORITY_AGENT
