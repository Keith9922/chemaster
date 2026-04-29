"""chem.kb MCP unit tests."""

from __future__ import annotations

import pytest

from chemaster.mcp.kb import server as kb_server


@pytest.fixture(autouse=True)
def _reset_doc_cache():
    """Each test starts with a fresh KB document cache."""
    kb_server._DOC_CACHE = None
    yield
    kb_server._DOC_CACHE = None


# ──────────────────────────────────────────────────────────────────────────
# kb_search
# ──────────────────────────────────────────────────────────────────────────


def test_kb_search_returns_hits():
    result = kb_server.kb_search(query="basis for transition metals", top_k=5)
    assert result["ok"]
    assert "hits" in result["result"]
    assert len(result["result"]["hits"]) > 0
    h = result["result"]["hits"][0]
    assert "doc_id" in h and "title" in h and "snippet" in h
    assert h["score"] > 0


def test_kb_search_finds_skills_too():
    """A query that matches an existing skill should rank it well."""
    result = kb_server.kb_search(query="opt freq frequency optimization", top_k=10)
    assert result["ok"]
    titles = [h["title"] for h in result["result"]["hits"]]
    assert any("opt-freq" in t.lower() for t in titles)


def test_kb_search_empty_query_returns_error():
    result = kb_server.kb_search(query="")
    assert not result["ok"]
    assert result["error_code"] == "EMPTY_QUERY"


def test_kb_search_no_hits_returns_warning():
    result = kb_server.kb_search(query="xxxxxxxxxxxxxxxxxxxxxxxx")
    assert result["ok"]
    assert result["result"]["hits"] == []
    assert any(w["code"] == "NO_HITS" for w in result["warnings"])


def test_kb_search_top_k_clamped():
    result = kb_server.kb_search(query="basis", top_k=100)
    assert result["ok"]
    assert len(result["result"]["hits"]) <= 20


# ──────────────────────────────────────────────────────────────────────────
# list_skills
# ──────────────────────────────────────────────────────────────────────────


def test_list_skills_returns_all_skills():
    result = kb_server.list_skills()
    assert result["ok"]
    skills = result["result"]["skills"]
    assert result["result"]["n_skills"] == len(skills)
    names = [s["name"] for s in skills]
    # We expect at least these.
    expected = {"opt-freq", "tadf-pipeline", "tddft", "soc"}
    assert expected.issubset(set(names)), f"missing: {expected - set(names)}"

    # Each entry has the expected shape
    for s in skills:
        assert "name" in s and "summary" in s and "source" in s
        assert s["source"].startswith("skills/")


# ──────────────────────────────────────────────────────────────────────────
# use_skill
# ──────────────────────────────────────────────────────────────────────────


def test_use_skill_get_info_returns_full_content():
    result = kb_server.use_skill(skill_name="opt-freq", action="get_info")
    assert result["ok"]
    assert result["result"]["name"] == "opt-freq"
    content = result["result"]["content"]
    assert "frequency" in content.lower() or "频率" in content
    fm = result["result"]["metadata"]
    assert fm.get("name") == "opt-freq"


def test_use_skill_get_metadata_only():
    result = kb_server.use_skill(skill_name="opt-freq", action="get_metadata")
    assert result["ok"]
    assert "content" not in result["result"]
    fm = result["result"]["metadata"]
    assert fm.get("name") == "opt-freq"


def test_use_skill_unknown_returns_error_with_suggestion():
    result = kb_server.use_skill(skill_name="never-existed", action="get_info")
    assert not result["ok"]
    assert result["error_code"] == "SKILL_NOT_FOUND"
    assert "Available skills" in result["suggestion"]
    assert "opt-freq" in result["suggestion"]


def test_use_skill_invalid_action():
    result = kb_server.use_skill(skill_name="opt-freq", action="banana")
    assert not result["ok"]
    assert result["error_code"] == "UNKNOWN_ACTION"


def test_use_skill_get_reference_missing_param():
    result = kb_server.use_skill(skill_name="opt-freq", action="get_reference")
    assert not result["ok"]
    assert result["error_code"] == "MISSING_REFERENCE"


def test_use_skill_get_reference_unknown_file():
    result = kb_server.use_skill(
        skill_name="opt-freq", action="get_reference", reference="does-not-exist.md",
    )
    assert not result["ok"]
    assert result["error_code"] == "REFERENCE_NOT_FOUND"


# ──────────────────────────────────────────────────────────────────────────
# Integration with the agent tool registry
# ──────────────────────────────────────────────────────────────────────────


def test_kb_tools_are_in_default_registry():
    from chemaster.agent.tool_loader import build_default_registry

    reg = build_default_registry()
    for name in ("kb_search", "use_skill", "list_skills"):
        assert reg.has(name), f"{name} not in registry"


def test_kb_search_via_tool_adapter():
    """The MCPToolAdapter should produce a clean ToolResult from kb_search."""
    from chemaster.agent.tool_loader import build_default_registry

    reg = build_default_registry()
    tool = reg.get("kb_search")
    assert tool is not None
    result = tool.run(query="basis", top_k=2)
    assert result.ok
    assert "kb_search" in result.observation
