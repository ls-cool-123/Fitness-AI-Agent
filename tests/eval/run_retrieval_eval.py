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

import argparse
import json
import math
import time
from pathlib import Path

import numpy as np
from langchain_qdrant import QdrantVectorStore, RetrievalMode

from agent.utils.config import config
from agent.utils.embeddings import get_embedding_model
from agent.utils.reranker import get_reranker
from agent.utils.vdb import qdrant_client, sparse_embeddings

# ── 加载评测集 ──────────────────────────────────────────────────────────
EVAL_FILE = Path(__file__).parent / "eval_queries.json"
with open(EVAL_FILE, encoding="utf-8") as f:
    EVAL_QUERIES = json.load(f)

DEFAULT_COLLECTION = "fitness_kb"
RETRIEVAL_K = config.retrieval_k  # 粗筛条数 (40)
TOP_K = 5  # 最终返回条数


def load_queries(path: str | None) -> list[dict]:
    """加载评测集；不传路径时用默认的 eval_queries.json。"""
    if not path:
        return EVAL_QUERIES
    with open(path, encoding="utf-8") as f:
        return json.load(f)

# ── 检索器工厂（绕过 retriever.py 缓存，为每个模式建独立实例）───


def _make_retriever(
    mode: RetrievalMode,
    collection: str = DEFAULT_COLLECTION,
    k: int = RETRIEVAL_K,
):
    """按指定检索模式创建检索器，不走缓存。"""
    embedding = get_embedding_model(config)
    vdb = QdrantVectorStore(
        client=qdrant_client,
        collection_name=collection,
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
    """Normalized DCG at K（二值相关：相关=1，不相关=0）。

    IDCG 按"标注的相关文档数"计算（``min(len(relevant), k)``），这是标准口径：
    如果实际有 5 条相关文档但只召回了 2 条，NDCG 应当因漏召回而被扣分。
    早期版本把 IDCG 建在"已召回的命中数"上，等于不惩罚漏召回，会让 NDCG
    在 Recall 下降时反而升高，面试时无法解释。
    """
    rel = [1 if rid in relevant_ids else 0 for rid in retrieved_ids[:k]]
    dcg = dcg_at_k(rel, k)
    ideal_hits = min(len(relevant_ids), k)
    ideal_rel = [1] * ideal_hits + [0] * (k - ideal_hits)
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


def _run_queries(
    retriever,
    use_rerank: bool,
    queries: list[dict],
) -> list[dict]:
    """对每条 query 跑一遍检索，返回逐条指标。

    只检索一次，总指标和分类指标都从这批结果里聚合——早期实现为了拿分类指标
    会把整个评测集重新检索一遍，重排模式下等于多花一倍时间（实测 32 分钟）。
    """
    reranker = get_reranker(provider=config.rerank_provider, top_k=TOP_K) if use_rerank else None
    rows: list[dict] = []

    for item in queries:
        query = item["query"]
        relevant = set(item["relevant_docs"])

        t0 = time.perf_counter()
        docs = retriever.invoke(query)
        retrieval_ms = (time.perf_counter() - t0) * 1000

        if use_rerank and reranker:
            # 与线上 rag_search_tool 一致：只把前 rerank_candidates 条交给重排
            candidates = docs[: config.rerank_candidates]
            # get_reranker 返回 (docs, scores) 元组，这里只取重排后的文档
            docs, _scores = reranker(candidates, query)
        else:
            docs = docs[:TOP_K]

        retrieved_ids = [d.metadata.get("_id") or str(d.id) for d in docs]
        rows.append(
            {
                "category": item.get("category", "unknown"),
                "recall": recall_at_k(relevant, retrieved_ids, TOP_K),
                "prec": precision_at_k(relevant, retrieved_ids, TOP_K),
                "mrr": mrr(relevant, retrieved_ids),
                "ndcg": ndcg_at_k(relevant, retrieved_ids, TOP_K),
                "latency": retrieval_ms,
            }
        )
    return rows


def _aggregate(rows: list[dict]) -> dict:
    """把逐条指标聚合成一行总指标。"""
    return {
        "召回率@5": round(float(np.mean([r["recall"] for r in rows])), 4),
        "精确率@5": round(float(np.mean([r["prec"] for r in rows])), 4),
        "平均倒数排名": round(float(np.mean([r["mrr"] for r in rows])), 4),
        "折损累计增益@5": round(float(np.mean([r["ndcg"] for r in rows])), 4),
        "平均延迟(ms)": round(float(np.mean([r["latency"] for r in rows])), 1),
    }


def evaluate(
    mode_name: str,
    retriever,
    use_rerank: bool = False,
    queries: list[dict] | None = None,
) -> tuple[dict, dict]:
    """单次检索同时产出总指标与分类指标。"""
    eval_queries = queries if queries is not None else EVAL_QUERIES
    rows = _run_queries(retriever, use_rerank, eval_queries)

    by_category: dict[str, list[dict]] = {}
    for row in rows:
        by_category.setdefault(row["category"], []).append(row)

    detail = {cat: _aggregate(cat_rows) for cat, cat_rows in by_category.items()}
    return _aggregate(rows), detail


# ── 主入口 ──────────────────────────────────────────────────────────────


def main(
    collection: str = DEFAULT_COLLECTION,
    queries: list[dict] | None = None,
    skip_rerank: bool = False,
    skip_flashrank: bool = False,
    rerank_provider_override: str = "",
) -> dict:
    eval_queries = queries if queries is not None else EVAL_QUERIES
    print("\n" + "=" * 80)
    print("  健身知识库检索质量评测")
    print(f"  评测集: {len(eval_queries)} 条 query | 知识库: {collection}")
    print(f"  粗筛: {RETRIEVAL_K} 条 → 最终返回: {TOP_K} 条")
    print("=" * 80)

    # ── 构建四种检索器 ──
    print("\n初始化检索器...")
    dense_retriever = _make_retriever(RetrievalMode.DENSE, collection)
    sparse_retriever = _make_retriever(RetrievalMode.SPARSE, collection)
    hybrid_retriever = _make_retriever(RetrievalMode.HYBRID, collection)

    # ── 运行五项实验 ──
    experiments = [
        ("A. Dense-only", dense_retriever, False, None),
        ("B. BM25-only", sparse_retriever, False, None),
        ("C. Hybrid (无重排)", hybrid_retriever, False, None),
        ("D. Hybrid+FlashRank", hybrid_retriever, True, "flashrank"),
        ("E. Hybrid+BGE", hybrid_retriever, True, "bge"),
    ]
    if skip_rerank:
        experiments = experiments[:3]
    elif skip_flashrank:
        experiments = [e for e in experiments if not e[0].startswith("D")]

    # 允许把 E 那一档换成别的重排器（例如远程的 siliconflow），
    # 这样同一份 query 可以在"本地 BGE / 远程 BGE"之间直接对比
    if rerank_provider_override:
        experiments = [
            (f"E. Hybrid+{rerank_provider_override}", hybrid_retriever, True, rerank_provider_override)
            if e[0].startswith("E")
            else e
            for e in experiments
        ]

    overall_results = {}
    detail_results = {}

    for name, retriever, use_rerank, rerank_provider in experiments:
        print(f"\n  评测 {name} ...", end=" ", flush=True)
        # 临时设置 rerank_provider，让本次实验使用指定的重排器
        orig_provider = config.rerank_provider
        if rerank_provider:
            config.rerank_provider = rerank_provider

        t0 = time.perf_counter()
        # 一次检索同时拿到总指标和分类指标（早期版本跑两遍，重排模式下慢一倍）
        result, detail = evaluate(name, retriever, use_rerank=use_rerank, queries=eval_queries)
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
    return overall_results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="检索质量评测（支持多 collection 对照）")
    parser.add_argument(
        "--collection",
        default=DEFAULT_COLLECTION,
        help="要评测的 Qdrant 集合，如 fitness_kb_b0 / fitness_kb_b1 / fitness_kb_b2",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="把结果写入 JSON 文件，便于多组实验汇总对比",
    )
    parser.add_argument(
        "--eval-file",
        default=None,
        help="自定义评测集 JSON（默认 tests/eval/eval_queries.json）",
    )
    parser.add_argument(
        "--skip-rerank",
        action="store_true",
        help="只跑 A/B/C 三种检索模式（离线环境下不加载 BGE/FlashRank 模型）",
    )
    parser.add_argument(
        "--skip-flashrank",
        action="store_true",
        help="跳过多余的 FlashRank 对照（已知中文场景失效，且需要额外下载模型）",
    )
    parser.add_argument(
        "--rerank-provider",
        default="",
        help="把重排那一档换成指定 provider（bge / siliconflow），用于本地与远程对比",
    )
    args = parser.parse_args()
    results = main(
        collection=args.collection,
        queries=load_queries(args.eval_file),
        skip_rerank=args.skip_rerank,
        skip_flashrank=args.skip_flashrank,
        rerank_provider_override=args.rerank_provider,
    )
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(
                {"collection": args.collection, "results": results},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"结果已写入 {output_path}")
