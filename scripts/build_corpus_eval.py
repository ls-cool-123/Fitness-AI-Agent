"""为新语料自动生成检索评测集。

背景：``eval_queries.json`` 里标注的是旧 16 篇语料的 point id，换了语料就用不了。
手工标注 60 篇文档的相关性太贵，这里用文档自身的一级标题作为 query、
该文档的所有 chunk 作为 relevant_docs，构成一组**文档级召回**评测集。

它测的不是"回答质量"，而是"给定文档标题，检索能否把这篇文档的片段排进 top-5"。
对分块方式、上下文前缀这类改动的差异足够敏感，也适合做 A/B 对照的快速回归。

用法：
    uv run python scripts/build_corpus_eval.py --collection fitness_kb_zh
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from loguru import logger

from agent.utils.vdb import qdrant_client


def _collect_chunks(collection: str) -> dict[str, list[str]]:
    """按 source 汇总每个文档的 chunk point id。"""
    by_source: dict[str, list[str]] = {}
    offset = None
    while True:
        points, offset = qdrant_client.scroll(
            collection_name=collection,
            limit=256,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for point in points:
            metadata = (point.payload or {}).get("metadata") or {}
            source = metadata.get("source")
            if source:
                by_source.setdefault(source, []).append(str(point.id))
        if offset is None:
            break
    return by_source


def _title_of(path: Path) -> str | None:
    """取 Markdown 的第一个一级标题。"""
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("# "):
                return stripped[2:].strip()
    except OSError:
        return None
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--collection", default="fitness_kb_zh")
    parser.add_argument("--root", default="data/knowledge")
    parser.add_argument(
        "--output", default="tests/eval/eval_queries_corpus.json"
    )
    args = parser.parse_args()

    by_source = _collect_chunks(args.collection)
    logger.info(f"{args.collection}: {len(by_source)} 篇文档")

    titles = {}
    for path in Path(args.root).rglob("*.md"):
        title = _title_of(path)
        if title:
            titles[path.name] = title

    queries: list[dict] = []
    for source, ids in sorted(by_source.items()):
        title = titles.get(source)
        if not title:
            continue
        queries.append(
            {
                "query": title,
                "category": "title_recall",
                "relevant_docs": ids,
            }
        )

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(queries, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"生成 {len(queries)} 条 query → {output}")


if __name__ == "__main__":
    main()
