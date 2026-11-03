"""把评测集里的 relevant_docs 映射到另一个集合的 point id。

同一批文档导入两个集合（比如 b0 旧分块 / zh 中文分块）时，point id 完全不同。
问题集是同一份，只需要把"相关文档"换成目标集合里的 id，就能保证两组实验
用的是**完全相同的 query**，指标才可比。

用法：
    uv run python scripts/remap_eval_ids.py \
        --eval tests/eval/eval_zh_llm.json \
        --collection fitness_kb_b0 \
        --output tests/eval/eval_b0_llm.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from loguru import logger

from agent.utils.vdb import qdrant_client


def _chunks_by_source(collection: str) -> dict[str, list[str]]:
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval", required=True, help="源评测集 JSON")
    parser.add_argument("--collection", required=True, help="目标集合")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    queries = json.loads(Path(args.eval).read_text(encoding="utf-8"))
    by_source = _chunks_by_source(args.collection)

    remapped = []
    dropped = 0
    for item in queries:
        source = item.get("source")
        ids = by_source.get(source or "")
        if not ids:
            dropped += 1
            continue
        remapped.append({**item, "relevant_docs": ids})

    Path(args.output).write_text(
        json.dumps(remapped, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info(
        f"{len(remapped)} 条 query 映射到 {args.collection}，丢弃 {dropped} 条（该集合里找不到来源文档）"
    )


if __name__ == "__main__":
    main()
