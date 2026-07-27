"""长期记忆召回工具。

让 Agent 能从用户的长期记忆中检索相关信息和偏好，
用于个性化回答和建议。
"""

from __future__ import annotations

import json

from langchain_core.tools import tool
from loguru import logger

# ------------------------------------------------------------------
# 延迟初始化 — 避免 import 时触发模型加载
# ------------------------------------------------------------------

_memory_retriever = None


def _get_retriever():
    """延迟初始化 MemoryRetriever 单例。"""
    global _memory_retriever
    if _memory_retriever is None:
        from agent.memory.retriever import MemoryRetriever  # noqa: PLC0415
        from agent.memory.store import MemoryStore  # noqa: PLC0415
        from agent.utils.config import config  # noqa: PLC0415

        store = MemoryStore(collection_name=config.memory_collection_name)
        _memory_retriever = MemoryRetriever(
            memory_store=store,
            broad_retrieval_k=40,
            default_half_life_days=config.memory_half_life_days,
        )
    return _memory_retriever


# ------------------------------------------------------------------
# Tool
# ------------------------------------------------------------------


@tool
async def recall_memories_tool(
    user_id: str,
    query: str,
    top_k: int = 5,
) -> str:
    """召回用户的历史偏好、目标和重要信息。

    当以下情况时使用此工具：
    - 需要了解用户的训练偏好、健身目标或身体数据
    - 用户问"我之前..."、"根据我的..."、"你知道我..."
    - 需要基于用户历史做个性化推荐或建议
    - 用户问到了之前讨论过的训练计划或目标

    **重要：** 此工具返回用户的长期记忆片段，
    请基于这些记忆给出个性化回答，让用户感受到你记住了他们的偏好和目标。

    Args:
        user_id: 用户唯一标识。
        query: 要搜索的用户上下文关键词（如"训练偏好""目标""伤病"）。
        top_k: 返回的相关记忆数量（默认5）。

    Returns:
        相关记忆的 JSON 字符串，每条含 content、relevance、memory_type、category、timestamp。
    """
    try:
        # ContextVar 强制鉴权
        from agent.tools import current_user_id  # noqa: PLC0415
        enforced = current_user_id.get()
        if enforced:
            user_id = enforced

        retriever = _get_retriever()
        results = await retriever.recall(
            query=query,
            user_id=user_id,
            top_k=top_k,
        )

        if not results:
            return json.dumps(
                {"status": "empty", "memories": [], "message": "暂无相关长期记忆"},
                ensure_ascii=False,
            )

        # 只保留对外有用的字段
        clean = []
        for r in results:
            clean.append({
                "content": r["content"],
                "relevance": r["relevance"],
                "memory_type": r["memory_type"],
                "category": r["category"],
                "timestamp": r["timestamp"],
            })

        logger.info(
            f"Recalled {len(clean)} memories for user={user_id}, query='{query[:50]}'"
        )
        return json.dumps(clean, ensure_ascii=False, indent=2)

    except Exception as e:
        logger.error(f"Memory recall failed: {e}")
        return json.dumps({"error": f"Memory recall failed: {e}"}, ensure_ascii=False)
