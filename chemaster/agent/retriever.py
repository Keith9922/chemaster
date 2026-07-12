"""KnowledgeRetriever — superseded by chem.kb MCP (kb_search / use_skill).

⚠️ Stub kept for backwards-compatible imports. The V2 architecture exposes
KB retrieval as agent tools (`kb_search`, `list_skills`, `use_skill`)
implemented in `chemaster.mcp.kb.server`. New code should not use this
class — call the MCP tools through the agent's tool registry instead.
"""

from __future__ import annotations

from pathlib import Path


class KnowledgeRetriever:
    """混合检索（BM25 + 向量）over kb/rules/."""

    def __init__(self, kb_root: str | Path | None = None) -> None:
        raise NotImplementedError("Phase 2: implement KnowledgeRetriever.")

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """检索，返回 [{text, source, score}, ...]。"""
        raise NotImplementedError("Phase 2.")
