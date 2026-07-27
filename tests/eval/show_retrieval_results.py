"""检索结果可视化 —— 逐条 query 展示不同模式的 top-5 文档排名。

用法：
  uv run python tests/eval/show_retrieval_results.py
  uv run python tests/eval/show_retrieval_results.py --query "深蹲膝盖内扣"
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from langchain_qdrant import QdrantVectorStore, RetrievalMode

from agent.utils.config import config
from agent.utils.embeddings import get_embedding_model
from agent.utils.reranker import get_reranker
from agent.utils.vdb import qdrant_client, sparse_embeddings

EVAL_FILE = Path(__file__).parent / "eval_queries.json"
OUTPUT_FILE = Path(__file__).parent / "retrieval_demo_output.txt"


def show_results(query_filter: str | None = None):
    with open(EVAL_FILE, encoding="utf-8") as f:
        queries = json.load(f)

    if query_filter:
        queries = [q for q in queries if query_filter in q["query"]]
        if not queries:
            print(f"未找到匹配 '{query_filter}' 的 query")

    # 构建检索器
    emb = get_embedding_model(config)
    vdb = QdrantVectorStore(
        client=qdrant_client,
        collection_name="fitness_kb",
        embedding=emb,
        sparse_embedding=sparse_embeddings,
        retrieval_mode=RetrievalMode.HYBRID,
        sparse_vector_name="fast-sparse-bm25",
    )
    retriever = vdb.as_retriever(search_kwargs={"k": 40})

    modes = [
        ("Hybrid (no rerank)", None),
        ("Hybrid+BGE", "bge"),
        ("Hybrid+FlashRank", "flashrank"),
    ]

    lines: list[str] = []

    for item in queries:
        query_text = item["query"]
        relevant_ids = set(item["relevant_docs"])

        lines.append("=" * 100)
        lines.append(f"Query: {query_text}")
        lines.append(f"相关文档: {len(relevant_ids)} 篇")
        lines.append("")

        # 粗筛
        docs = retriever.invoke(query_text)

        for mode_name, provider in modes:
            lines.append(f"--- {mode_name} ---")
            lines.append(f"{'排名':<5s} {'文档ID':<38s} {'命中':<6s} {'内容摘要'}")

            if provider:
                orig = config.rerank_provider
                config.rerank_provider = provider
                reranker = get_reranker(provider=provider, top_k=5)
                top_docs = reranker(docs, query_text)
                config.rerank_provider = orig
            else:
                top_docs = docs[:5]

            for rank, d in enumerate(top_docs, 1):
                doc_id = d.metadata.get("_id") or str(d.id)
                is_hit = "[HIT]" if doc_id in relevant_ids else "[MISS]"
                snippet = (d.page_content or "")[:100].replace("\n", " ")
                lines.append(f"{rank:<5d} {doc_id:<38s} {is_hit:<6s} {snippet}...")

            # 统计该模式的命中数
            hit_count = sum(
                1 for d in top_docs if (d.metadata.get("_id") or str(d.id)) in relevant_ids
            )
            lines.append(f"→ top-5 命中 {hit_count}/{len(relevant_ids)} 篇相关文档")
            lines.append("")

        lines.append("")

    # 输出
    output = "\n".join(lines)
    OUTPUT_FILE.write_text(output, encoding="utf-8")
    print(output)
    print(f"\n结果已保存到: {OUTPUT_FILE}")


if __name__ == "__main__":
    filter_arg = sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == "--query" else None
    show_results(filter_arg)
