"""把 HuggingFace 缓存里的模型"落地"成普通目录。

为什么需要这个：仓库里的 hf_cache / fastembed_cache 是在 Linux 容器里下载的，
快照目录里的文件是指向 blobs 的符号链接。这些链接在 Windows 上无法解析
（表现为大小为 0、读取时报 WinError 1920），于是 sentence-transformers 会以为
模型不存在，转头去连 huggingface.co——离线环境直接失败。

本脚本用 HF API 拿到「文件名 → blob 哈希」的映射，再把 blob 硬链接（同盘时）
或复制成普通文件，得到一个可以直接传给 CrossEncoder / FastEmbedSparse 的本地目录。

用法：
    uv run python scripts/materialize_hf_model.py \
        --repo BAAI/bge-reranker-v2-m3 \
        --cache hf_cache/hub \
        --out resources/bge_reranker
"""

from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

from huggingface_hub import HfApi
from loguru import logger


def _cache_blob_dir(cache_root: Path, repo: str) -> Path:
    """按 HF 缓存命名规则拼出 blobs 目录：models--<org>--<name>/blobs。"""
    org, name = repo.split("/", 1)
    return cache_root / f"models--{org}--{name}" / "blobs"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, help="模型仓库名，如 BAAI/bge-reranker-v2-m3")
    parser.add_argument("--cache", default="hf_cache/hub", help="HF hub 缓存目录")
    parser.add_argument("--out", required=True, help="输出目录")
    parser.add_argument(
        "--copy",
        action="store_true",
        help="改用复制而不是硬链接（跨盘时必须）",
    )
    args = parser.parse_args()

    cache_root = Path(args.cache).resolve()
    out_dir = Path(args.out).resolve()
    blobs = _cache_blob_dir(cache_root, args.repo)

    if not blobs.exists():
        raise SystemExit(f"找不到缓存目录: {blobs}")

    api = HfApi()
    info = api.model_info(args.repo, files_metadata=True)

    # 本地 blob 的命名不一定等于 API 给的 blob_id（xet 存储会另算哈希），
    # 因此再建一张「体积 → blob 路径」的索引，按大小兜底匹配。
    size_index: dict[int, Path] = {}
    for path in blobs.iterdir():
        if path.is_file():
            size_index.setdefault(path.stat().st_size, path)

    linked = 0
    skipped = 0
    for sibling in info.siblings or []:
        blob_id = sibling.blob_id
        filename = sibling.rfilename
        if not blob_id:
            skipped += 1
            continue

        src = blobs / blob_id
        if not src.exists() and sibling.size:
            src = size_index.get(sibling.size, src)
        if not src.exists():
            logger.warning(f"blob 缺失，跳过 {filename}")
            skipped += 1
            continue

        dst = out_dir / filename
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            dst.unlink()
        if args.copy:
            shutil.copy2(src, dst)
        else:
            try:
                os.link(src, dst)
            except OSError:
                # 跨盘或文件系统不支持硬链接时退回复制
                shutil.copy2(src, dst)
        linked += 1

    logger.info(f"完成：{linked} 个文件落地到 {out_dir}，跳过 {skipped} 个")


if __name__ == "__main__":
    main()
