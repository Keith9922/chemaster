"""User knowledge base — let researchers extend ChemMaster's KB with their
own skills, rules and software preferences.

Layout under ``~/.chemaster/user_kb/`` (created on first use):

    ~/.chemaster/user_kb/
      prefs.yaml                  # software/tool preferences (this user's policy)
      rules/<*.yaml>              # custom rule sheets (basis sets, functionals, ...)
      skills/<name>/SKILL.md      # custom skill playbooks
      notes/<*.md>                # free-form notes

Loading model:

* All user docs are merged into the same in-memory corpus that the built-in
  KB uses, with an extra ``user_provided=True`` flag in their meta block so
  the Agent (and the UI) can distinguish them from shipped content.
* ``prefs.yaml`` is loaded separately and surfaced to the Agent via a
  dedicated tool / system prompt note so that method-selection
  recommendations respect the researcher's standing preferences.

The mechanism solves two issues raised in the advisor-feedback round:

1. **Domain-specific knowledge that the foundation model does not know** —
   the user uploads a SKILL.md describing the workflow for their specific
   molecule family; the Agent searches it at runtime through ``kb_search``.

2. **Researcher software/tool preferences** — the user declares
   ``spectroscopy: BDF`` / ``ground_state_dft: Gaussian`` in ``prefs.yaml``;
   the Agent reads those preferences before emitting ``recommend`` cards.

This module owns *discovery, path resolution, and file IO*; the actual
search/scoring continues to live in ``chemaster.mcp.kb.server``.
"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# Paths
# ══════════════════════════════════════════════════════════════════════════════


def user_kb_root() -> Path:
    """Resolve the user-KB root directory.

    Honoured environment overrides (in priority order):
      * ``CHEMASTER_USER_KB_DIR`` — explicit override path
      * ``CHEMASTER_HOME`` — overrides the ``~/.chemaster`` base
      * default: ``~/.chemaster/user_kb``
    """
    explicit = os.environ.get("CHEMASTER_USER_KB_DIR")
    if explicit:
        return Path(explicit).expanduser()
    base = os.environ.get("CHEMASTER_HOME")
    if base:
        return Path(base).expanduser() / "user_kb"
    return Path.home() / ".chemaster" / "user_kb"


def user_kb_subdir(name: str, create: bool = False) -> Path:
    """Return ``<user_kb_root>/<name>`` and optionally mkdir -p."""
    path = user_kb_root() / name
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def user_kb_prefs_path() -> Path:
    return user_kb_root() / "prefs.yaml"


def ensure_user_kb_layout() -> Path:
    """Create the expected directory layout on first use.

    Returns the root path. Idempotent.
    """
    root = user_kb_root()
    root.mkdir(parents=True, exist_ok=True)
    for sub in ("rules", "skills", "notes"):
        (root / sub).mkdir(exist_ok=True)
    return root


# ══════════════════════════════════════════════════════════════════════════════
# Preferences
# ══════════════════════════════════════════════════════════════════════════════


# Canonical preference categories that the Agent may consult. The keys are
# intentionally informal — researchers think in terms of tasks like
# "spectroscopy" and "ground-state DFT" rather than tool names.
KNOWN_PREF_CATEGORIES: tuple[str, ...] = (
    "ground_state_dft",
    "excited_state_tddft",
    "soc",
    "tvcf_rate",
    "wavefunction_analysis",
    "semi_empirical",
    "conformer_search",
    "coupled_cluster",
    "solvation_model",
    "default_basis",
    "default_functional",
)


@dataclass
class UserPreferences:
    """Parsed contents of ``user_kb/prefs.yaml``.

    Example file::

        # ~/.chemaster/user_kb/prefs.yaml
        ground_state_dft: Gaussian
        excited_state_tddft: Gaussian
        soc: BDF                      # I always use BDF for SOC
        tvcf_rate: MOMAP
        default_functional: B3LYP-D3(BJ)
        default_basis: def2-TZVP
        notes:
          - "For our P=O OLED emitters, use ωB97X-D for CT states."
    """

    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def categories(self) -> dict[str, str]:
        """Just the recognised category → tool mappings."""
        return {
            k: str(v)
            for k, v in self.raw.items()
            if k in KNOWN_PREF_CATEGORIES and v is not None
        }

    @property
    def notes(self) -> list[str]:
        n = self.raw.get("notes") or []
        if isinstance(n, str):
            return [n]
        return [str(x) for x in n if x is not None]

    def get(self, category: str, default: str | None = None) -> str | None:
        """Look up the preferred tool for a category, with fuzzy fallback.

        Tries exact match first, then case-insensitive, then synonyms.
        """
        if category in self.raw:
            return str(self.raw[category])
        lowered = category.lower()
        for k, v in self.raw.items():
            if k.lower() == lowered:
                return str(v)
        # Synonyms for common phrasings
        synonym_map = {
            "spectroscopy": "tvcf_rate",
            "spectra": "tvcf_rate",
            "absorption": "excited_state_tddft",
            "emission": "tvcf_rate",
            "fluorescence": "tvcf_rate",
            "phosphorescence": "tvcf_rate",
            "relativistic": "soc",
            "spin_orbit": "soc",
            "ground": "ground_state_dft",
            "optimize": "ground_state_dft",
            "excited": "excited_state_tddft",
            "tddft": "excited_state_tddft",
        }
        canon = synonym_map.get(lowered)
        if canon and canon in self.raw:
            return str(self.raw[canon])
        return default

    def as_system_prompt_snippet(self) -> str:
        """Render preferences as a chunk to append to the Agent system prompt.

        Returns an empty string if no recognised preferences are set, so the
        Agent receives nothing rather than an empty header.
        """
        cats = self.categories
        notes = self.notes
        if not cats and not notes:
            return ""
        lines = ["## User preferences (from ~/.chemaster/user_kb/prefs.yaml)",
                 ""]
        if cats:
            lines.append("Preferred tools by task category:")
            for k, v in cats.items():
                lines.append(f"- {k}: {v}")
            lines.append("")
        if notes:
            lines.append("Additional researcher notes:")
            for n in notes:
                lines.append(f"- {n}")
            lines.append("")
        lines.append(
            "When emitting `recommend` cards, prefer the user's tools above "
            "unless there is a specific technical reason against (e.g. the "
            "method is not supported in that engine). Always state which "
            "preference you are honouring in the recommendation reasoning."
        )
        return "\n".join(lines)


def load_user_prefs() -> UserPreferences:
    """Read ``prefs.yaml`` and return a parsed UserPreferences.

    Returns an empty UserPreferences if the file does not exist or is empty.
    Silently swallows YAML errors after logging.
    """
    path = user_kb_prefs_path()
    if not path.exists():
        return UserPreferences()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        logger.warning("Failed to parse %s: %s", path, exc)
        return UserPreferences()
    if not isinstance(raw, dict):
        logger.warning("%s did not parse to a mapping (got %s); ignored",
                       path, type(raw).__name__)
        return UserPreferences()
    return UserPreferences(raw=raw)


def save_user_prefs(prefs: UserPreferences) -> Path:
    """Write the preferences back to disk. Creates layout if missing."""
    ensure_user_kb_layout()
    path = user_kb_prefs_path()
    path.write_text(yaml.safe_dump(prefs.raw, allow_unicode=True,
                                     sort_keys=False, default_flow_style=False),
                    encoding="utf-8")
    return path


# ══════════════════════════════════════════════════════════════════════════════
# Adding user-provided docs
# ══════════════════════════════════════════════════════════════════════════════


def add_user_doc(source: Path | str, kind: str = "auto",
                  dest_name: str | None = None) -> Path:
    """Copy a user-provided document into the user KB.

    Args:
        source:    Local path to the file to import.
        kind:      "auto" (infer from extension), "skill", "rules", or "notes".
        dest_name: Optional override for the destination filename / folder.

    Returns:
        The final destination path.

    Layout:
        kind="skill"  → user_kb/skills/<dest_name>/SKILL.md
        kind="rules"  → user_kb/rules/<dest_name>.yaml
        kind="notes"  → user_kb/notes/<dest_name>.md
    """
    source = Path(source).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f"User doc source does not exist: {source}")
    if not source.is_file():
        raise ValueError(f"User doc source is not a file: {source}")

    ensure_user_kb_layout()

    if kind == "auto":
        ext = source.suffix.lower()
        if ext in (".yaml", ".yml"):
            kind = "rules"
        elif ext == ".md" and "skill" in source.stem.lower():
            kind = "skill"
        elif ext == ".md":
            kind = "notes"
        else:
            raise ValueError(
                f"Cannot infer kind from extension {ext!r}; "
                "pass kind='skill' | 'rules' | 'notes' explicitly."
            )

    if kind == "skill":
        base = dest_name or source.stem.replace(" ", "_").lower()
        target_dir = user_kb_subdir("skills", create=True) / base
        target_dir.mkdir(exist_ok=True)
        dest = target_dir / "SKILL.md"
    elif kind == "rules":
        base = dest_name or source.stem.replace(" ", "_").lower()
        dest = user_kb_subdir("rules", create=True) / f"{base}.yaml"
    elif kind == "notes":
        base = dest_name or source.stem.replace(" ", "_").lower()
        dest = user_kb_subdir("notes", create=True) / f"{base}.md"
    else:
        raise ValueError(f"Unknown kind {kind!r}")

    shutil.copyfile(source, dest)
    logger.info("Added user doc %s → %s", source, dest)
    return dest


def list_user_docs() -> dict[str, list[str]]:
    """Return {"rules": [...], "skills": [...], "notes": [...]}."""
    root = user_kb_root()
    if not root.exists():
        return {"rules": [], "skills": [], "notes": []}
    out: dict[str, list[str]] = {}
    rules_dir = root / "rules"
    out["rules"] = sorted([
        p.name for p in rules_dir.glob("*.y*ml") if p.is_file()
    ]) if rules_dir.exists() else []
    skills_dir = root / "skills"
    out["skills"] = sorted([
        p.name for p in skills_dir.iterdir() if p.is_dir() and (p / "SKILL.md").exists()
    ]) if skills_dir.exists() else []
    notes_dir = root / "notes"
    out["notes"] = sorted([
        p.name for p in notes_dir.glob("*.md") if p.is_file()
    ]) if notes_dir.exists() else []
    return out


def remove_user_doc(kind: str, name: str) -> bool:
    """Delete a user-provided doc by kind+name. Returns True if removed."""
    if kind == "skill":
        target = user_kb_subdir("skills") / name
        if target.exists() and target.is_dir():
            shutil.rmtree(target)
            return True
    elif kind == "rules":
        for ext in (".yaml", ".yml"):
            target = user_kb_subdir("rules") / f"{name}{ext}"
            if target.exists() and target.is_file():
                target.unlink()
                return True
    elif kind == "notes":
        target = user_kb_subdir("notes") / f"{name}.md"
        if target.exists() and target.is_file():
            target.unlink()
            return True
    return False
