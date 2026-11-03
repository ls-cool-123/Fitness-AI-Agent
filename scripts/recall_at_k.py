"""粗筛候选数的覆盖率曲线：决定重排要喂多少条。

BGE 重排在 CPU 上很慢（40 条约 30 秒），所以想尽量少喂。问题是少喂会不会漏掉
本该被重排"捞上来"的文档。这里直接看不同截断位置的 Recall@K——它就是重排的
理论上限：第 K 名之外的文档，重排再好也选不到。

用法：
    uv run python scripts/recall_at_k.py --collection fitness_kb_zh --eval-file tests/eval/eval_zh_llm.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from langchain_qdrant import QdrantVectorStore, RetrievalMode

from agent.utils.config import config
from agent.utils.embeddings import get_embedding_model
from agent.utils.vdb import qdrant_client, sparse_embeddings

KS = (5, 10, 15, 20, 30, 40)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--collection", default="fitness_kb_zh")
    parser.add_argument("--eval-file", default="tests/eval/eval_zh_llm.json")
    parser.add_argument("--depth", type=int, default=40)
    args = parser.parse_args()

    queries = json.loads(Path(args.eval_file).read_text(encoding="utf-8"))

    retriever = QdrantVectorStore(
        client=qdrant_client,
        collection_name=args.collection,
        embedding=get_embedding_model(config),
        sparse_embedding=sparse_embeddings,
        retrieval_mode=RetrievalMode.HYBRID,
        sparse_vector_name="fast-sparse-bm25",
    ).as_retriever(search_kwargs={"k": args.depth})

    totals = dict.fromkeys(KS, 0.0)
    for item in queries:
        relevant = set(item["relevant_docs"])
        ids = [d.metadata.get("_id") or str(d.id) for d in retriever.invoke(item["query"])]
        for k in KS:
            hits = sum(1 for rid in ids[:k] if rid in relevant)
            totals[k] += hits / len(relevant) if relevant else 0.0

    print(f"\n{args.collection} | {len(queries)} 条 query | 文档级相关性")
    print(f"{'K':>4}{'Recall@K':>12}")
    for k in KS:
        print(f"{k:>4}{totals[k] / len(queries):>12.4f}")


if __name__ == "__main__":
    main()
