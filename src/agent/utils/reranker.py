"""Reranker utilities for document reranking.

Supported providers:
  - "bge"       : BGE-reranker-v2-m3 (BAAI, 多语言, 免费, 本地)
  - "flashrank" : ms-marco-MiniLM-L-12-v2 (英文 only, 免费, 本地)
  - "none"      : passthrough (no reranking)
"""

import math
from typing import TYPE_CHECKING, Literal

from langchain_core.documents import Document
from loguru import logger

if TYPE_CHECKING:
    from flashrank import Ranker

RerankerProvider = Literal["bge", "flashrank", "none"]

# ── BGE Reranker (多语言, 中文友好) ────────────────────────────────────

_bge_ranker = None  # sentence_transformers CrossEncoder


def _get_bge_ranker():
    """Get or create cached BGE reranker via sentence-transformers CrossEncoder."""
    global _bge_ranker
    if _bge_ranker is None:
        from sentence_transformers import CrossEncoder  # noqa: PLC0415

        _bge_ranker = CrossEncoder(
            "BAAI/bge-reranker-v2-m3",
        )
        logger.info("BGE-reranker-v2-m3 model loaded and cached")
    return _bge_ranker


def rerank_with_bge(
    documents: list[Document], query: str, top_k: int
) -> tuple[list[Document], list[float]]:
    """Rerank using BGE-reranker-v2-m3 (multilingual cross-encoder).

    BGE 将 query 和每个 doc 拼接成 [query, doc] pair，用 CrossEncoder
    做二分类打分（相关/不相关）。

    分数经 sigmoid 归一化到 (0, 1) 区间，与 memory retriever 保持一致，
    便于设置统一的分数阈值过滤低质量 chunk。

    Returns:
        (reranked_docs, scores): 重排后的文档列表及每条文档的归一化得分 (0-1)。
    """
    if not documents:
        return documents, []

    ranker = _get_bge_ranker()

    # 构建 (query, doc) pair 列表
    pairs = [[query, doc.page_content] for doc in documents]

    # CrossEncoder.predict 返回每个 pair 的原始 logits（约 -10 ~ 10）
    raw_scores = ranker.predict(pairs, show_progress_bar=False)

    # 单条结果统一为列表
    if not hasattr(raw_scores, "__iter__"):
        raw_scores = [raw_scores]

    # sigmoid 归一化到 (0, 1)，与 memory retriever._rerank() 保持一致
    normalized = [1.0 / (1.0 + math.exp(-s)) for s in raw_scores]

    # 按分数降序排列，取 top_k
    ranked = sorted(enumerate(normalized), key=lambda x: x[1], reverse=True)[:top_k]

    reranked_docs = [documents[idx] for idx, _ in ranked]
    reranked_scores = [normalized[idx] for idx, _ in ranked]

    logger.info(f"BGE reranked {len(documents)} documents to top {len(reranked_docs)}")
    return reranked_docs, reranked_scores


# ── FlashRank Reranker (英文 only, 保留作为对比基线) ──────────────────

_flashrank_ranker: "Ranker | None" = None


def _get_flashrank_ranker() -> "Ranker":
    """Get or create cached FlashRank ranker."""
    global _flashrank_ranker
    if _flashrank_ranker is None:
        from flashrank import Ranker  # noqa: PLC0415

        _flashrank_ranker = Ranker(model_name="ms-marco-MiniLM-L-12-v2", cache_dir="/tmp/flashrank")
        logger.info("FlashRank model loaded and cached")
    return _flashrank_ranker


def rerank_with_flashrank(
    documents: list[Document], query: str, top_k: int
) -> tuple[list[Document], list[float]]:
    """Rerank documents using FlashRank (local model, English only)."""
    from flashrank import RerankRequest  # noqa: PLC0415

    if not documents:
        return documents, []

    ranker = _get_flashrank_ranker()

    passages = [{"id": i, "text": doc.page_content, "meta": doc.metadata} for i, doc in enumerate(documents)]

    rerank_request = RerankRequest(query=query, passages=passages)
    results = ranker.rerank(rerank_request)

    sorted_results = sorted(results, key=lambda x: x["score"], reverse=True)[:top_k]

    reranked_docs = []
    reranked_scores = []
    for result in sorted_results:
        reranked_docs.append(documents[result["id"]])
        reranked_scores.append(result["score"])

    logger.info(f"FlashRank reranked {len(documents)} documents to top {len(reranked_docs)}")
    return reranked_docs, reranked_scores


# ── Factory ────────────────────────────────────────────────────────────


def get_reranker(
    provider: RerankerProvider,
    top_k: int = 3,
) -> callable:
    """Get a reranker function based on the provider.

    All providers return (list[Document], list[float]) — reranked docs
    and their corresponding scores.

    Args:
        provider: "bge" / "flashrank" / "none"
        top_k: Number of top documents to return after reranking.

    Returns:
        A callable that takes (documents, query) and returns
        (reranked_documents, scores).

    """
    match provider:
        case "none":
            logger.info("Reranking disabled, using passthrough")
            return lambda docs, _: (
                (docs[:top_k], [1.0] * min(top_k, len(docs)))
            )

        case "flashrank":
            _get_flashrank_ranker()
            return lambda docs, query: rerank_with_flashrank(docs, query, top_k)

        case "bge":
            return lambda docs, query: rerank_with_bge(docs, query, top_k)

        case _:
            msg = f"Unknown reranker provider: {provider}"
            raise ValueError(msg)
