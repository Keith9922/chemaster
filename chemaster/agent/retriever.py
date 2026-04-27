"""KnowledgeRetriever —— 对 chemaster/kb/rules/ 做 RAG 检索。

Phase 2 实现。给 Planner 提供"基组/泛函/收敛/工作流"等经验规则。
"""

from __future__ import annotations

from pathlib import Path


class KnowledgeRetriever:
    """混合检索（BM25 + 向量）over kb/rules/."""

    def __init__(self, kb_root: str | Path = None) -> None:  # noqa: ARG002
        raise NotImplementedError("Phase 2: implement KnowledgeRetriever.")

    def search(self, query: str, top_k: int = 5) -> list[dict]:  # noqa: ARG002
        """检索，返回 [{text, source, score}, ...]。"""
        raise NotImplementedError("Phase 2.")
