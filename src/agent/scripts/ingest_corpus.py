"""批量导入知识库语料。

用于构建 A/B 对照集合，例如：

    # 基线：旧配置（英文分隔符、无上下文前缀）
    uv run python -m agent.scripts.ingest_corpus --root data/knowledge \
        --collection fitness_kb_b0 --legacy-split --no-contextual --recreate

    # 只修中文分块
    uv run python -m agent.scripts.ingest_corpus --root data/knowledge \
        --collection fitness_kb_b1 --no-contextual --recreate

    # 中文分块 + Contextual Retrieval
    uv run python -m agent.scripts.ingest_corpus --root data/knowledge \
        --collection fitness_kb_b2 --contextual --recreate

三个集合的 chunk 数会随配置不同而不同，评测脚本用
``--collection`` 分别跑，就能拆出每一步各自的贡献。
"""

from __future__ import annotations

import argparse
import shutil
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from agent.backend.services.embedding_management import EmbeddingManagement
from agent.utils.config import config
from agent.utils.vdb import qdrant_client

# 旧版分隔符：只有英文标点，用于复现改造前的基线
_LEGACY_SEPARATORS = ["\n\n", "\n", ".", "!"]


def _recreate_collection(collection: str) -> None:
    """删掉同名集合，保证本次导入从零开始（避免 A/B 两组混在一起）。"""
    if qdrant_client.collection_exists(collection_name=collection):
        qdrant_client.delete_collection(collection_name=collection)
        logger.info(f"已删除旧集合 {collection}")


def _copy_root(source: Path, target: Path) -> Path:
    """把语料复制到临时目录，避免导入过程改动源文件。"""
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description="批量导入语料到 Qdrant")
    parser.add_argument("--root", default="data/knowledge", help="语料根目录")
    parser.add_argument("--collection", required=True, help="目标集合名")
    parser.add_argument("--recreate", action="store_true", help="导入前删除同名集合")
    parser.add_argument(
        "--contextual",
        dest="contextual",
        action="store_true",
        help="启用 Contextual Retrieval（每个 chunk 生成上下文前缀）",
    )
    parser.add_argument(
        "--no-contextual",
        dest="contextual",
        action="store_false",
        help="关闭 Contextual Retrieval（基线/中间组用）",
    )
    parser.add_argument(
        "--legacy-split",
        action="store_true",
        help="用改造前的英文分隔符分块（复现基线）",
    )
    parser.add_argument("--chunk-size", type=int, default=None)
    parser.add_argument("--chunk-overlap", type=int, default=None)
    parser.set_defaults(contextual=config.contextual_retrieval_enabled)

    args = parser.parse_args()

    # 运行期覆盖配置：pydantic settings 实例允许赋值
    config.contextual_retrieval_enabled = args.contextual
    if args.legacy_split:
        config.chunk_separators = _LEGACY_SEPARATORS
    if args.chunk_size:
        config.chunk_size = args.chunk_size
    if args.chunk_overlap is not None:
        config.chunk_overlap = args.chunk_overlap

    if args.recreate:
        _recreate_collection(args.collection)

    upload_time = datetime.now(timezone.utc).isoformat()
    service = EmbeddingManagement(collection_name=args.collection)

    logger.info(
        f"开始导入 {args.root} → {args.collection} "
        f"(contextual={config.contextual_retrieval_enabled}, "
        f"chunk={config.chunk_size}/{config.chunk_overlap}, "
        f"legacy_split={args.legacy_split})"
    )
    total = service.embed_directory_tree(args.root, upload_time=upload_time)

    count = qdrant_client.count(collection_name=args.collection).count
    logger.info(f"导入完成：本次写入 {total} 个 chunk，集合当前共 {count} 个点")


if __name__ == "__main__":
    main()
