"""chem.kb MCP server.

Three tools the Agent uses to query the chemistry knowledge base:

- `kb_search(query)`  — full-text search over kb/rules/*.yaml + kb/skills/*/SKILL.md
- `list_skills()`     — list available skills with one-line summaries
- `use_skill(name, action="get_info" | "get_reference", reference=None)`
                      — read a skill's full content or a referenced sub-doc

This MCP intentionally uses **no** vector index. A simple BM25-ish term-frequency
scoring is enough for our corpus size (< 50 documents) and avoids dragging in
heavy embedding deps. Easy to swap for a real RAG later.

Reference: EvoMaster's SkillTool (skill-as-tool, not skill-as-architectural-layer).
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)
mcp = FastMCP("chem.kb")


# ══════════════════════════════════════════════════════════════════════════════
# KB locations
# ══════════════════════════════════════════════════════════════════════════════


def _kb_root() -> Path:
    """Resolve the KB directory: chemaster/kb/ next to this MCP package."""
    return Path(__file__).resolve().parents[2] / "kb"


def _rules_dir() -> Path:
    return _kb_root() / "rules"


def _skills_dir() -> Path:
    return _kb_root() / "skills"


# ══════════════════════════════════════════════════════════════════════════════
# Document loading + caching
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class _Doc:
    doc_id: str           # unique id ("rules/basis_sets.yaml#STO-3G" or "skills/opt-freq")
    source: str           # file path, relative
    kind: str             # "rule" | "skill"
    title: str
    text: str             # plain text used for scoring
    meta: dict[str, Any]


_DOC_CACHE: list[_Doc] | None = None


def _load_docs() -> list[_Doc]:
    global _DOC_CACHE
    if _DOC_CACHE is not None:
        return _DOC_CACHE
    docs: list[_Doc] = []

    # Rules: each YAML is a list-of-things (basis sets / functionals / etc.).
    # We index per-item so kb_search can return the relevant entry.
    rules_dir = _rules_dir()
    if rules_dir.exists():
        for yfile in sorted(rules_dir.glob("*.yaml")):
            try:
                content = yaml.safe_load(yfile.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError as exc:
                logger.warning("skipping %s: %s", yfile.name, exc)
                continue
            relpath = yfile.relative_to(_kb_root()).as_posix()
            for top_key, items in (content or {}).items():
                if isinstance(items, list):
                    for it in items:
                        if not isinstance(it, dict):
                            continue
                        item_name = it.get("name") or it.get("title") or it.get("id") or ""
                        text = _yaml_item_to_text(it)
                        docs.append(_Doc(
                            doc_id=f"{relpath}#{item_name}" if item_name else relpath,
                            source=relpath,
                            kind="rule",
                            title=f"{top_key}: {item_name}".strip(": "),
                            text=text,
                            meta={"top_key": top_key, **it},
                        ))
                else:
                    docs.append(_Doc(
                        doc_id=relpath,
                        source=relpath,
                        kind="rule",
                        title=top_key,
                        text=str(items),
                        meta={"top_key": top_key, "value": items},
                    ))

    # Skills: each <name>/SKILL.md is one document.
    skills_dir = _skills_dir()
    if skills_dir.exists():
        for sk_dir in sorted(p for p in skills_dir.iterdir() if p.is_dir()):
            skill_md = sk_dir / "SKILL.md"
            if not skill_md.exists():
                continue
            text = skill_md.read_text(encoding="utf-8")
            front, body = _split_frontmatter(text)
            docs.append(_Doc(
                doc_id=f"skills/{sk_dir.name}",
                source=skill_md.relative_to(_kb_root()).as_posix(),
                kind="skill",
                title=front.get("name", sk_dir.name),
                text=body,
                meta={"frontmatter": front, "skill_dir": str(sk_dir)},
            ))

    # User-provided KB (~/.chemaster/user_kb/) — merged with the built-in corpus
    # so the Agent can `kb_search` over both transparently.
    docs.extend(_load_user_docs())

    _DOC_CACHE = docs
    logger.info("KB loaded: %d docs (%d skills, %d rule entries, %d user-provided)",
                len(docs),
                sum(1 for d in docs if d.kind == "skill"),
                sum(1 for d in docs if d.kind == "rule"),
                sum(1 for d in docs if d.meta.get("user_provided")))
    return docs


def _load_user_docs() -> list[_Doc]:
    """Load user-provided docs from ``~/.chemaster/user_kb/``.

    Returns an empty list if the user KB is absent.
    """
    try:
        from chemaster.agent.user_kb import user_kb_root
    except ImportError:
        return []

    root = user_kb_root()
    if not root.exists():
        return []

    docs: list[_Doc] = []

    # User rules: same structure as built-in rules (top-level mapping of lists)
    user_rules = root / "rules"
    if user_rules.exists():
        for yfile in sorted(user_rules.glob("*.y*ml")):
            try:
                content = yaml.safe_load(yfile.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError as exc:
                logger.warning("skipping user rules %s: %s", yfile.name, exc)
                continue
            relpath = f"user_kb/rules/{yfile.name}"
            for top_key, items in (content or {}).items():
                if isinstance(items, list):
                    for it in items:
                        if not isinstance(it, dict):
                            continue
                        item_name = it.get("name") or it.get("title") or ""
                        docs.append(_Doc(
                            doc_id=f"{relpath}#{item_name}" if item_name else relpath,
                            source=relpath,
                            kind="rule",
                            title=f"{top_key}: {item_name}".strip(": "),
                            text=_yaml_item_to_text(it),
                            meta={"top_key": top_key, "user_provided": True, **it},
                        ))
                else:
                    docs.append(_Doc(
                        doc_id=relpath,
                        source=relpath,
                        kind="rule",
                        title=top_key,
                        text=str(items),
                        meta={"top_key": top_key, "value": items,
                              "user_provided": True},
                    ))

    # User skills: <name>/SKILL.md, same as built-in.
    user_skills = root / "skills"
    if user_skills.exists():
        for sk_dir in sorted(p for p in user_skills.iterdir() if p.is_dir()):
            skill_md = sk_dir / "SKILL.md"
            if not skill_md.exists():
                continue
            text = skill_md.read_text(encoding="utf-8")
            front, body = _split_frontmatter(text)
            docs.append(_Doc(
                doc_id=f"user_kb/skills/{sk_dir.name}",
                source=f"user_kb/skills/{sk_dir.name}/SKILL.md",
                kind="skill",
                title=front.get("name", sk_dir.name),
                text=body,
                meta={"frontmatter": front, "skill_dir": str(sk_dir),
                      "user_provided": True},
            ))

    # User notes: flat *.md files — indexed as skill-like documents.
    user_notes = root / "notes"
    if user_notes.exists():
        for md in sorted(user_notes.glob("*.md")):
            text = md.read_text(encoding="utf-8")
            docs.append(_Doc(
                doc_id=f"user_kb/notes/{md.stem}",
                source=f"user_kb/notes/{md.name}",
                kind="skill",          # treat as searchable doc
                title=md.stem,
                text=text,
                meta={"user_provided": True, "doc_type": "note"},
            ))

    return docs


def reset_doc_cache() -> None:
    """Force the next ``_load_docs`` call to re-read from disk.

    Used by unit tests and the CLI's ``kb reload`` subcommand.
    """
    global _DOC_CACHE
    _DOC_CACHE = None


def _yaml_item_to_text(item: dict) -> str:
    """Flatten a YAML item (dict) into a searchable text blob."""
    parts: list[str] = []
    for k, v in item.items():
        if isinstance(v, list):
            v_str = " ".join(str(x) for x in v)
        elif isinstance(v, dict):
            v_str = " ".join(f"{kk}={vv}" for kk, vv in v.items())
        else:
            v_str = str(v)
        parts.append(f"{k}: {v_str}")
    return "\n".join(parts)


def _split_frontmatter(text: str) -> tuple[dict, str]:
    """Parse `---\\n...\\n---\\n<body>`. Returns (frontmatter_dict, body_str)."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    fm_text = text[3:end]
    body = text[end + 4:].lstrip("\n")
    try:
        fm = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError:
        fm = {}
    return fm if isinstance(fm, dict) else {}, body


# ══════════════════════════════════════════════════════════════════════════════
# Scoring (lightweight BM25-style)
# ══════════════════════════════════════════════════════════════════════════════


_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.\-]*")


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


# 实验室自定义文档（~/.chemaster/user_kb/）在同等匹配度下应排在通用参考之前：
# 用户写进自己 KB 的方法约定，就是希望 agent 优先看到的。
USER_DOC_BOOST = 1.3


def _score(query_tokens: list[str], doc: _Doc) -> float:
    if not query_tokens:
        return 0.0
    haystack = (doc.title + "\n" + doc.text).lower()
    haystack_tokens = _tokenize(haystack)
    if not haystack_tokens:
        return 0.0
    counts = Counter(haystack_tokens)
    score = 0.0
    for q in query_tokens:
        # Title match boosted.
        if q in doc.title.lower():
            score += 3.0
        score += counts.get(q, 0) * 1.0
        # Substring fallback for terms like "B3LYP" inside compound text.
        if q not in counts and q in haystack:
            score += 0.5
    if doc.meta.get("user_provided"):
        score *= USER_DOC_BOOST
    return score


# ══════════════════════════════════════════════════════════════════════════════
# Tools
# ══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
def kb_search(query: str, top_k: int = 5) -> dict[str, Any]:
    """Search the chemistry knowledge base.

    Searches rules (basis sets, functionals, convergence settings, workflows)
    and skill summaries together. Returns the top-k snippets with citations,
    so the Agent can cite specific KB entries when planning.

    When to use:
        - Before choosing a method/basis the user didn't specify.
        - When recovering from UNSUPPORTED_ELEMENT errors.
        - When deciding how to handle a user-described workflow.

    When NOT to use:
        - To do arithmetic. Use chem.const.convert_unit instead.
        - To run a calculation. The KB is informational only.

    Args:
        query: free-form natural language query
               (e.g. "basis for transition metals", "TADF skill", "TDA T1").
        top_k: how many results to return (default 5, capped at 20).

    Returns:
        {
          "ok": True,
          "result": {
              "query": "...",
              "hits": [
                {"doc_id": "...", "kind": "rule"|"skill",
                 "title": "...", "source": "rules/...yaml#...",
                 "score": 4.5, "snippet": "..."}
              ],
          },
          "warnings": [],
        }
    """
    if not query or not query.strip():
        return {
            "ok": False,
            "error_code": "EMPTY_QUERY",
            "details": "kb_search needs a non-empty query string.",
            "suggestion": "Pass a natural-language query, e.g. 'basis for Pt'.",
        }
    top_k = max(1, min(int(top_k or 5), 20))
    docs = _load_docs()
    qtoks = _tokenize(query)
    scored = [(_score(qtoks, d), d) for d in docs]
    scored = [(s, d) for s, d in scored if s > 0]
    scored.sort(key=lambda x: x[0], reverse=True)
    hits = []
    for s, d in scored[:top_k]:
        hits.append({
            "doc_id": d.doc_id,
            "kind": d.kind,
            "title": d.title,
            "source": d.source,
            "score": round(s, 3),
            "snippet": _make_snippet(d.text, qtoks, length=400),
        })
    return {
        "ok": True,
        "result": {"query": query, "hits": hits, "n_total_docs": len(docs)},
        "warnings": [] if hits else [{"code": "NO_HITS", "message": f"No KB entries match '{query}'."}],
        "meta": {"engine": "chem.kb v1 (term-frequency)"},
    }


@mcp.tool()
def list_skills() -> dict[str, Any]:
    """List all available chemistry skills with one-line summaries.

    Use this when planning a new task and you want to see what playbooks the
    KB has. Then call use_skill(name, action='get_info') on the relevant ones
    to read full details.

    Returns:
        {"ok": True, "result": {"skills": [{"name", "summary", "source"}, ...]}}
    """
    docs = _load_docs()
    # User notes share kind="skill" so kb_search/use_skill can reach them,
    # but they are not playbooks — keep them out of the skill catalogue.
    skills = [
        d for d in docs
        if d.kind == "skill" and d.meta.get("doc_type") != "note"
    ]
    payload = []
    for d in skills:
        fm = d.meta.get("frontmatter", {}) or {}
        summary = (
            fm.get("description")
            or _first_nonempty_line(d.text)
            or "(no description)"
        )
        payload.append({
            "name": fm.get("name") or d.doc_id.split("/")[-1],
            "summary": summary,
            "source": d.source,
            "version": fm.get("version", ""),
        })
    return {
        "ok": True,
        "result": {"skills": payload, "n_skills": len(payload)},
        "warnings": [],
        "meta": {},
    }


@mcp.tool()
def use_skill(skill_name: str, action: str = "get_info", reference: str = "") -> dict[str, Any]:
    """Read a skill (playbook) by name.

    Args:
        skill_name: skill directory name, e.g. "opt-freq", "tadf-pipeline".
        action: one of:
            - "get_info"      → return the full SKILL.md content
            - "get_reference" → return a referenced markdown file under the
                                 skill's `references/` subdir (set `reference`).
            - "get_metadata"  → just the frontmatter (lightweight)
        reference: filename when action="get_reference" (e.g. "convergence.md").

    Returns:
        {"ok": True, "result": {"name", "action", "content", "metadata"}}
        On error: {"ok": False, "error_code": "...", ...}.
    """
    docs = _load_docs()
    skill_doc = next(
        (d for d in docs if d.kind == "skill" and (
            d.title == skill_name
            or d.doc_id == f"skills/{skill_name}"
            or d.meta.get("frontmatter", {}).get("name") == skill_name
        )),
        None,
    )
    if skill_doc is None:
        names = [d.title for d in docs if d.kind == "skill"]
        return {
            "ok": False,
            "error_code": "SKILL_NOT_FOUND",
            "details": f"No skill named {skill_name!r}.",
            "suggestion": f"Available skills: {', '.join(sorted(names))}",
        }

    fm = skill_doc.meta.get("frontmatter", {}) or {}

    if action == "get_metadata":
        return {
            "ok": True,
            "result": {"name": skill_name, "action": action, "metadata": fm},
            "warnings": [], "meta": {"source": skill_doc.source},
        }

    if action == "get_info":
        return {
            "ok": True,
            "result": {
                "name": skill_name,
                "action": action,
                "metadata": fm,
                "content": skill_doc.text,
            },
            "warnings": [],
            "meta": {"source": skill_doc.source},
        }

    if action == "get_reference":
        if not reference:
            return {
                "ok": False,
                "error_code": "MISSING_REFERENCE",
                "details": "action='get_reference' requires reference=<filename>.",
                "suggestion": "Call use_skill(name, action='get_info') first "
                              "— the skill body lists its references/ files; "
                              "then pass one as reference=.",
            }
        ref_path = Path(skill_doc.meta["skill_dir"]) / "references" / reference
        if not ref_path.exists():
            avail = []
            ref_dir = Path(skill_doc.meta["skill_dir"]) / "references"
            if ref_dir.exists():
                avail = sorted(p.name for p in ref_dir.iterdir() if p.is_file())
            return {
                "ok": False,
                "error_code": "REFERENCE_NOT_FOUND",
                "details": f"{reference!r} not found in skill {skill_name!r}.",
                "suggestion": f"Available references: {', '.join(avail) or '(none)'}",
            }
        return {
            "ok": True,
            "result": {
                "name": skill_name,
                "action": action,
                "reference": reference,
                "content": ref_path.read_text(encoding="utf-8"),
            },
            "warnings": [],
            "meta": {"source": str(ref_path.relative_to(_kb_root()))},
        }

    return {
        "ok": False,
        "error_code": "UNKNOWN_ACTION",
        "details": f"Unknown action {action!r}.",
        "suggestion": "Pick one of: get_info, get_metadata, get_reference.",
    }


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════


def _make_snippet(text: str, query_tokens: list[str], length: int = 300) -> str:
    """Pull a short window around the first query-term hit."""
    if not text:
        return ""
    lower = text.lower()
    pos = -1
    for q in query_tokens:
        idx = lower.find(q)
        if idx != -1 and (pos == -1 or idx < pos):
            pos = idx
    if pos == -1:
        return text[:length]
    start = max(0, pos - length // 4)
    end = min(len(text), pos + length * 3 // 4)
    snippet = text[start:end].replace("\n", " ").strip()
    if start > 0:
        snippet = "…" + snippet
    if end < len(text):
        snippet = snippet + "…"
    return snippet


def _first_nonempty_line(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return line[:200]
    return ""


# ══════════════════════════════════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════════════════════════════════


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
