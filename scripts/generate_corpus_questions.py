"""用 LLM 为语料生成"改写式"评测问题。

为什么不用标题：标题原文会出现在 chunk 开头，任何检索方式都能命中，
指标直接饱和（Recall@5 = 1.0），测不出分块/上下文前缀的差异。

这里让 LLM 读每篇文档正文，生成一个**真实用户会问、但不照抄标题**的问题，
再用该文档的所有 chunk 作为 relevant_docs，构成一组有区分度的检索评测集。

用法：
    uv run python scripts/generate_corpus_questions.py --collection fitness_kb_zh
"""

from __future__ import annotations

import argparse
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from loguru import logger

from agent.utils.vdb import qdrant_client

PROMPT = """你是健身 App 的用户。读完下面这篇知识库文档，提出一个你**真的会问**的问题。

硬性要求：
1. 用中文，20–40 字，像聊天，不像考试题；
2. 不要照抄文档标题，也不要把标题里的连续 8 个字原样搬进问题；
3. 必须得靠文档正文里的具体做法或数字才能回答；
4. 只输出问题本身，不要编号、引号或解释。

文档标题：{title}
文档正文：
{body}
"""


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


def _read_doc(path: Path) -> tuple[str, str]:
    """读出标题与正文（去掉标题行）。"""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    title = ""
    body_lines = []
    for line in lines:
        if not title and line.strip().startswith("# "):
            title = line.strip()[2:].strip()
            continue
        body_lines.append(line)
    return title, "\n".join(body_lines).strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--collection", default="fitness_kb_zh")
    parser.add_argument("--root", default="data/knowledge")
    parser.add_argument("--output", default="tests/eval/eval_queries_llm.json")
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()

    from agent.agent.fitness_agent import _create_llm  # noqa: PLC0415
    from agent.utils.config import config  # noqa: PLC0415

    llm = _create_llm(config, streaming=False)
    by_source = _collect_chunks(args.collection)
    logger.info(f"{args.collection}: {len(by_source)} 篇文档")

    docs = []
    for path in sorted(Path(args.root).rglob("*.md")):
        if path.name == "README.md" or path.name not in by_source:
            continue
        title, body = _read_doc(path)
        if title and body:
            docs.append((path.name, title, body, by_source[path.name]))

    def _ask(item: tuple[str, str, str, list[str]]) -> dict | None:
        name, title, body, ids = item
        prompt = PROMPT.format(title=title, body=body[:2500])
        try:
            raw = llm.invoke(prompt)
            question = str(getattr(raw, "content", raw)).strip()
            # 去掉模型偶尔加上的引号/编号
            question = re.sub(r'^[\d\.\、\s"“”]+', "", question).strip().strip('"“”')
            if not question:
                return None
            return {
                "query": question,
                "category": Path(name).stem.split("-")[0],
                "source": name,
                "relevant_docs": ids,
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"生成失败 {name}: {exc}")
            return None

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = [r for r in pool.map(_ask, docs) if r]

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"生成 {len(results)} 条 query → {output}")


if __name__ == "__main__":
    main()
