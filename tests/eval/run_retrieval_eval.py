"""检索质量评测 —— 对比四种检索模式在 fitness_kb 上的表现。

四种模式：
  A. Dense-only      — 纯稠密向量语义检索
  B. BM25-only       — 纯 BM25 稀疏向量关键词检索
  C. Hybrid          — 稠密 + BM25 混合检索（当前默认）
  D. Hybrid+Rerank   — 混合检索 + FlashRank 重排序

指标：召回率@5, 精确率@5, 平均倒数排名, 折损累计增益@5

用法：
  uv run python tests/eval/run_retrieval_eval.py
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

import numpy as np
from langchain_qdrant import QdrantVectorStore, RetrievalMode
from loguru import logger

from agent.utils.config import config
from agent.utils.embeddings import get_embedding_model
from agent.utils.reranker import get_reranker
from agent.utils.vdb import qdrant_client, sparse_embeddings

# ── 加载评测集 ──────────────────────────────────────────────────────────
EVAL_FILE = Path(__file__).parent / "eval_queries.json"
with open(EVAL_FILE, encoding="utf-8") as f:
    EVAL_QUERIES = json.load(f)

COLLECTION = "fitness_kb"
RETRIEVAL_K = config.retrieval_k  # 粗筛条数 (40)
TOP_K = 5  # 最终返回条数

# ── 检索器工厂（绕过 retriever.py 缓存，为每个模式建独立实例）───


def _make_retriever(mode: RetrievalMode, k: int = RETRIEVAL_K):
    """按指定检索模式创建检索器，不走缓存。"""
    embedding = get_embedding_model(config)
    vdb = QdrantVectorStore(
        client=qdrant_client,
        collection_name=COLLECTION,
        embedding=embedding,
        sparse_embedding=sparse_embeddings,
        retrieval_mode=mode,
        sparse_vector_name="fast-sparse-bm25",
    )
    return vdb.as_retriever(search_kwargs={"k": k})


# ── 评测指标计算 ────────────────────────────────────────────────────────


def dcg_at_k(relevance: list[int], k: int) -> float:
    """Discounted Cumulative Gain at K."""
    return sum(
        rel / math.log2(i + 2)
        for i, rel in enumerate(relevance[:k])
    )


def ndcg_at_k(relevant_ids: set[str], retrieved_ids: list[str], k: int) -> float:
    """Normalized DCG at K（二值相关：相关=1，不相关=0）。"""
    rel = [1 if rid in relevant_ids else 0 for rid in retrieved_ids[:k]]
    dcg = dcg_at_k(rel, k)
    ideal_rel = sorted(rel, reverse=True)
    idcg = dcg_at_k(ideal_rel, k)
    return dcg / idcg if idcg > 0 else 0.0


def recall_at_k(relevant_ids: set[str], retrieved_ids: list[str], k: int) -> float:
    """前 K 条中覆盖了多少比例的相关文档。"""
    if not relevant_ids:
        return 0.0
    hits = sum(1 for rid in retrieved_ids[:k] if rid in relevant_ids)
    return hits / len(relevant_ids)


def precision_at_k(relevant_ids: set[str], retrieved_ids: list[str], k: int) -> float:
    """前 K 条中相关文档的占比。"""
    top_k = retrieved_ids[:k]
    if not top_k:
        return 0.0
    hits = sum(1 for rid in top_k if rid in relevant_ids)
    return hits / len(top_k)


def mrr(relevant_ids: set[str], retrieved_ids: list[str]) -> float:
    """Mean Reciprocal Rank —— 第一个相关文档排在第几位。"""
    for rank, rid in enumerate(retrieved_ids, 1):
        if rid in relevant_ids:
            return 1.0 / rank
    return 0.0


# ── 评测主流程 ──────────────────────────────────────────────────────────


def evaluate_mode(
    mode_name: str,
    retriever,
    use_rerank: bool = False,
) -> dict:
    """对评测集中每条 query 检索并计算四项指标，返回均值。"""
    reranker = get_reranker(provider=config.rerank_provider, top_k=TOP_K) if use_rerank else None

    recall_scores: list[float] = []
    prec_scores: list[float] = []
    mrr_scores: list[float] = []
    ndcg_scores: list[float] = []
    latencies: list[float] = []

    for item in EVAL_QUERIES:
        query = item["query"]
        relevant = set(item["relevant_docs"])

        t0 = time.perf_counter()
        docs = retriever.invoke(query)
        retrieval_ms = (time.perf_counter() - t0) * 1000

        if use_rerank and reranker:
            docs = reranker(docs, query)
        else:
            docs = docs[:TOP_K]

        retrieved_ids = [d.metadata.get("_id") or str(d.id) for d in docs]

        recall_scores.append(recall_at_k(relevant, retrieved_ids, TOP_K))
        prec_scores.append(precision_at_k(relevant, retrieved_ids, TOP_K))
        mrr_scores.append(mrr(relevant, retrieved_ids))
        ndcg_scores.append(ndcg_at_k(relevant, retrieved_ids, TOP_K))
        latencies.append(retrieval_ms)

    return {
        "召回率@5": round(np.mean(recall_scores), 4),
        "精确率@5": round(np.mean(prec_scores), 4),
        "平均倒数排名": round(np.mean(mrr_scores), 4),
        "折损累计增益@5": round(np.mean(ndcg_scores), 4),
        "平均延迟(ms)": round(np.mean(latencies), 1),
    }


# ── 按 category 细分评测 ─────────────────────────────────────────────────


def evaluate_by_category(mode_name: str, retriever, use_rerank: bool = False) -> dict:
    """按 query 类别分别统计指标。"""
    reranker = get_reranker(provider=config.rerank_provider, top_k=TOP_K) if use_rerank else None

    categories: dict[str, dict[str, list[float]]] = {}

    for item in EVAL_QUERIES:
        cat = item["category"]
        if cat not in categories:
            categories[cat] = {"recall": [], "prec": [], "mrr": [], "ndcg": []}

        query = item["query"]
        relevant = set(item["relevant_docs"])

        docs = retriever.invoke(query)
        if use_rerank and reranker:
            docs = reranker(docs, query)
        else:
            docs = docs[:TOP_K]

        retrieved_ids = [d.metadata.get("_id") or str(d.id) for d in docs]

        categories[cat]["recall"].append(recall_at_k(relevant, retrieved_ids, TOP_K))
        categories[cat]["prec"].append(precision_at_k(relevant, retrieved_ids, TOP_K))
        categories[cat]["mrr"].append(mrr(relevant, retrieved_ids))
        categories[cat]["ndcg"].append(ndcg_at_k(relevant, retrieved_ids, TOP_K))

    result = {}
    for cat, scores in categories.items():
        result[cat] = {
            "召回率@5": round(np.mean(scores["recall"]), 4),
            "精确率@5": round(np.mean(scores["prec"]), 4),
            "平均倒数排名": round(np.mean(scores["mrr"]), 4),
            "折损累计增益@5": round(np.mean(scores["ndcg"]), 4),
        }
    return result


# ── 主入口 ──────────────────────────────────────────────────────────────


def main():
    print("\n" + "=" * 80)
    print("  健身知识库 (fitness_kb) 检索质量评测")
    print(f"  评测集: {len(EVAL_QUERIES)} 条 query | 知识库: {COLLECTION} (16 docs)")
    print(f"  粗筛: {RETRIEVAL_K} 条 → 最终返回: {TOP_K} 条")
    print("=" * 80)

    # ── 构建四种检索器 ──
    print("\n初始化检索器...")
    dense_retriever = _make_retriever(RetrievalMode.DENSE)
    sparse_retriever = _make_retriever(RetrievalMode.SPARSE)
    hybrid_retriever = _make_retriever(RetrievalMode.HYBRID)

    # ── 运行五项实验 ──
    experiments = [
        ("A. Dense-only", dense_retriever, False, None),
        ("B. BM25-only", sparse_retriever, False, None),
        ("C. Hybrid (无重排)", hybrid_retriever, False, None),
        ("D. Hybrid+FlashRank", hybrid_retriever, True, "flashrank"),
        ("E. Hybrid+BGE", hybrid_retriever, True, "bge"),
    ]

    overall_results = {}
    detail_results = {}

    for name, retriever, use_rerank, rerank_provider in experiments:
        print(f"\n  评测 {name} ...", end=" ", flush=True)
        # 临时设置 rerank_provider，保证 evaluate_mode 和 evaluate_by_category 使用同一个
        orig_provider = config.rerank_provider
        if rerank_provider:
            config.rerank_provider = rerank_provider

        t0 = time.perf_counter()
        result = evaluate_mode(name, retriever, use_rerank=use_rerank)
        detail = evaluate_by_category(name, retriever, use_rerank=use_rerank)
        elapsed = time.perf_counter() - t0

        # 恢复原值
        config.rerank_provider = orig_provider

        print(f"({elapsed:.1f}s)")
        overall_results[name] = result
        detail_results[name] = detail

    # ── 输出总表 ──
    print("\n" + "=" * 80)
    print("  总体指标对比")
    print("=" * 80)
    header = f"  {'模式':<22s} {'召回率@5':>8s} {'精确率@5':>8s} {'平均倒数排名':>10s} {'折损累计增益@5':>14s} {'平均延迟':>8s}"
    print(header)
    print("  " + "-" * 74)

    for name, r in overall_results.items():
        print(
            f"  {name:<22s} "
            f"{r['召回率@5']:>8.4f} "
            f"{r['精确率@5']:>8.4f} "
            f"{r['平均倒数排名']:>10.4f} "
            f"{r['折损累计增益@5']:>14.4f} "
            f"{r['平均延迟(ms)']:>6.0f}ms"
        )

    # ── 提升幅度对比 ──
    hybrid = overall_results.get("C. Hybrid (无重排)", {})
    dense = overall_results.get("A. Dense-only", {})
    bge = overall_results.get("E. Hybrid+BGE", {})
    flash = overall_results.get("D. Hybrid+FlashRank", {})

    if dense and hybrid:
        print("\n" + "-" * 80)
        print("  提升幅度分析")
        print("-" * 80)
        for metric in ["召回率@5", "精确率@5", "平均倒数排名", "折损累计增益@5"]:
            db = dense.get(metric, 0)
            hb = hybrid.get(metric, 0)
            bb = bge.get(metric, 0)
            fb = flash.get(metric, 0)
            delta_hd = ((hb - db) / db * 100) if db > 0 else 0
            delta_bh = ((bb - hb) / hb * 100) if hb > 0 else 0
            delta_fh = ((fb - hb) / hb * 100) if hb > 0 else 0
            print(
                f"  {metric:<14s}: "
                f"Dense→Hybrid  {db:.4f}→{hb:.4f}  ({delta_hd:+.1f}%)  |  "
                f"+BGE  {hb:.4f}→{bb:.4f}  ({delta_bh:+.1f}%)  |  "
                f"+FlashRank  {hb:.4f}→{fb:.4f}  ({delta_fh:+.1f}%)"
            )

    # ── 按类别细分 ──
    print("\n" + "=" * 80)
    print("  按主题类别细分 (Hybrid+BGE)")
    print("=" * 80)
    cat_header = f"  {'类别':<10s} {'召回率@5':>8s} {'精确率@5':>8s} {'平均倒数排名':>10s} {'折损累计增益@5':>14s}"
    print(cat_header)
    print("  " + "-" * 54)
    if "E. Hybrid+BGE" in detail_results:
        for cat, scores in detail_results["E. Hybrid+BGE"].items():
            print(
                f"  {cat:<10s} "
                f"{scores['召回率@5']:>8.4f} "
                f"{scores['精确率@5']:>8.4f} "
                f"{scores['平均倒数排名']:>10.4f} "
                f"{scores['折损累计增益@5']:>14.4f}"
            )

    print("\n" + "=" * 80)
    print("  评测完成。")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
