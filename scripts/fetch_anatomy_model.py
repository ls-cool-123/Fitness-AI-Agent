"""下载并瘦身 3D 人体模型（一次性脚本）。

模型来源：hpfrei/body-anatomy-3d-viewer 的 ``public/body.glb``，由 Z-Anatomy
简化而来，CC BY-SA 4.0。原始文件 8.2 MB，其中 JSON chunk 占了 6.8 MB——绝大部分
是每根骨头/每块肌肉的维基描述。浏览器只需要 ``type/name/nameDetail`` 做分组，
所以这里删掉 description/wikiLink/cross-section 字段后重新打包，通常能压到
1.5~3 MB，能过 pre-commit 的 5 MB 单文件上限。

用法：
    uv run python scripts/fetch_anatomy_model.py
"""

from __future__ import annotations

import base64
import hashlib
import json
import shutil
import struct
import sys
import urllib.request
from pathlib import Path

REPO = "hpfrei/body-anatomy-3d-viewer"
MODEL_PATH = "public/body.glb"
BLOB_SHA = "78c1f5bda9feba5577c85872f33257c99b789ef8"
EXPECTED_SHA256 = "0886b6a068e655b284903664e2178d7964f80b1c0ce798461909ac806bcef2e3"
MAX_BYTES = 5_000_000

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "frontend" / "public" / "models" / "body.glb"
ATTRIBUTION = ROOT / "frontend" / "public" / "models" / "ATTRIBUTION.md"
DRACO_SRC = ROOT / "frontend" / "node_modules" / "three" / "examples" / "jsm" / "libs" / "draco"
DRACO_DEST = ROOT / "frontend" / "public" / "draco"
DRACO_ATTRIBUTION = DRACO_DEST / "ATTRIBUTION.md"

JSON_CHUNK = 0x4E4F534A
BIN_CHUNK = 0x004E4942


def download_blob() -> bytes:
    """通过 GitHub Git Blob API 下载原始 GLB 并校验哈希。"""
    url = f"https://api.github.com/repos/{REPO}/git/blobs/{BLOB_SHA}"
    request = urllib.request.Request(  # noqa: S310 - 固定 HTTPS 地址
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "fitness-ai-agent-anatomy-fetch",
        },
    )
    with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("encoding") != "base64":
        raise RuntimeError("GitHub 返回的不是 base64 blob，检查 API 响应")
    data = base64.b64decode(payload["content"])
    digest = hashlib.sha256(data).hexdigest()
    if digest != EXPECTED_SHA256:
        raise RuntimeError(f"模型哈希不匹配：{digest} != {EXPECTED_SHA256}")
    return data


def read_glb(data: bytes) -> tuple[dict, list[tuple[int, bytes]]]:
    """拆出 GLB 的 JSON 与其余 chunk（保持顺序）。"""
    magic, version, _length = struct.unpack_from("<4sII", data, 0)
    if magic != b"glTF" or version != 2:
        raise RuntimeError("不是 glTF 2.0 GLB 文件")

    offset = 12
    gltf: dict | None = None
    chunks: list[tuple[int, bytes]] = []
    while offset < len(data):
        length, chunk_type = struct.unpack_from("<II", data, offset)
        offset += 8
        chunk = data[offset : offset + length]
        offset += length
        if chunk_type == JSON_CHUNK:
            gltf = json.loads(chunk.rstrip(b" \t\r\n\0"))
        else:
            chunks.append((chunk_type, chunk))

    if gltf is None:
        raise RuntimeError("GLB 缺少 JSON chunk")
    return gltf, chunks


def strip_extras(value: object) -> None:
    """递归删除 extras 里的长文本，只保留分组所需字段。"""
    if isinstance(value, dict):
        extras = value.get("extras")
        if isinstance(extras, dict):
            keep = {key: extras[key] for key in ("type", "name", "nameDetail") if key in extras}
            value["extras"] = keep
        for item in list(value.values()):
            strip_extras(item)
    elif isinstance(value, list):
        for item in value:
            strip_extras(item)


def pack_glb(gltf: dict, chunks: list[tuple[int, bytes]]) -> bytes:
    """把瘦身后的 JSON 与原始 BIN chunk 重新打包成 GLB。"""
    json_bytes = json.dumps(gltf, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    json_pad = (-len(json_bytes)) % 4
    json_bytes += b" " * json_pad

    all_chunks: list[tuple[int, bytes]] = [(JSON_CHUNK, json_bytes)]
    for chunk_type, chunk in chunks:
        pad = (-len(chunk)) % 4
        all_chunks.append((chunk_type, chunk + (b"\x00" * pad if chunk_type == BIN_CHUNK else b" " * pad)))

    total = 12 + sum(8 + len(chunk) for _, chunk in all_chunks)
    output = bytearray(struct.pack("<4sII", b"glTF", 2, total))
    for chunk_type, chunk in all_chunks:
        output += struct.pack("<II", len(chunk), chunk_type)
        output += chunk
    return bytes(output)


def write_attribution() -> None:
    """模型是 CC BY-SA 4.0，必须随资产保留来源与许可。"""
    ATTRIBUTION.write_text(
        "# 3D 人体模型来源与许可\n\n"
        "本目录的 `body.glb` 下载自并改编自：\n\n"
        "- 模型仓库：https://github.com/hpfrei/body-anatomy-3d-viewer\n"
        "- 原始模型作者：hpfrei（CC BY-SA 4.0）\n"
        "- 上游数据：Z-Anatomy（https://www.z-anatomy.com/，CC BY-SA 4.0）\n\n"
        "## 修改说明\n\n"
        "原始文件 8,249,484 bytes，Git blob SHA `78c1f5bda9feba5577c85872f33257c99b789ef8`，"
        "SHA256 `0886b6a068e655b284903664e2178d7964f80b1c0ce798461909ac806bcef2e3`。\n\n"
        "本项目通过 `scripts/fetch_anatomy_model.py`：\n\n"
        "1. 删除每个节点 `extras` 中的 `description`、`wikiLink` 与 cross-section 字段；\n"
        "2. 只保留 `type`、`name`、`nameDetail` 用于按肌肉群分组；\n"
        "3. 重新打包 GLB，几何/BIN 数据未改动。\n\n"
        "## 许可\n\n"
        "本模型及其改编版本按 **CC BY-SA 4.0** 分发：\n"
        "https://creativecommons.org/licenses/by-sa/4.0/\n\n"
        "应用代码与模型资产是分开的；使用/分发模型时请保留本文件并注明修改。\n",
        encoding="utf-8",
    )


def copy_draco() -> None:
    """从 three 包里复制 DRACO 解码器，模型是 Draco 压缩的。"""
    if not DRACO_SRC.is_dir():
        print(f"[warn] 找不到 {DRACO_SRC}，请先执行 `cd frontend && npm install three`，然后重跑本脚本")
        return
    DRACO_DEST.mkdir(parents=True, exist_ok=True)
    for name in ("draco_decoder.js", "draco_decoder.wasm", "draco_wasm_wrapper.js"):
        source = DRACO_SRC / name
        if source.is_file():
            shutil.copy2(source, DRACO_DEST / name)
    DRACO_ATTRIBUTION.write_text(
        "# DRACO 解码器来源\n\n"
        "本目录的 `draco_decoder.js`、`draco_decoder.wasm`、`draco_wasm_wrapper.js` 由\n"
        "`scripts/fetch_anatomy_model.py` 从 `three` npm 包的 "
        "`examples/jsm/libs/draco/` 复制而来。\n\n"
        "- three.js: https://github.com/mrdoob/three.js\n"
        "- DRACO: https://github.com/google/draco\n"
        "- 许可：Apache License 2.0\n\n"
        "它们只用于在浏览器里解码 `../models/body.glb` 的 Draco 压缩几何数据。\n",
        encoding="utf-8",
    )
    print(f"DRACO decoder copied to {DRACO_DEST}")


def main() -> int:
    print(f"Downloading {REPO}/{MODEL_PATH} ...")
    original = download_blob()
    print(f"Original: {len(original):,} bytes (sha256 verified)")

    gltf, chunks = read_glb(original)
    strip_extras(gltf)
    slimmed = pack_glb(gltf, chunks)
    print(f"Slimmed: {len(slimmed):,} bytes")
    if len(slimmed) >= MAX_BYTES:
        print(f"[error] 瘦身后仍超过 {MAX_BYTES:,} bytes，先降低模型精度再入库")
        return 1

    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_bytes(slimmed)
    write_attribution()
    copy_draco()
    print(f"Wrote {DEST}")
    print(f"New sha256: {hashlib.sha256(slimmed).hexdigest()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
