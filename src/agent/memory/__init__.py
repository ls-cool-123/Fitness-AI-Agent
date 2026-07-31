"""长期记忆模块。

提供用户长期记忆的全生命周期管理：
- 从对话中自动提取有价值的记忆
- 重要性评审后持久化到 Qdrant
- 通过 recall_memories_tool 召回并应用于对话

主要入口:
- extract_and_store_memories(): 异步 fire-and-forget 记忆提取
"""

from __future__ import annotations

from agent.memory.extractor import (
    extract_memories,
    format_conversation_for_extraction,
    score_importance,
)
from agent.memory.models import MemoryCandidate, MemoryPayload, MemorySearchResult, ScoredMemory
from agent.memory.retriever import MemoryRetriever
from agent.memory.store import MemoryStore

__all__ = [
    "MemoryStore",
    "MemoryRetriever",
    "MemoryCandidate",
    "ScoredMemory",
    "MemoryPayload",
    "MemorySearchResult",
    "extract_memories",
    "score_importance",
    "format_conversation_for_extraction",
    "extract_and_store_memories",
]


async def extract_and_store_memories(
    user_id: str,
    langchain_messages: list,
) -> None:
    """从对话中提取记忆并持久化（异步 fire-and-forget）。

    在每次对话后调用，作为后台任务运行，不阻塞用户响应。

    流程:
    1. 格式化最近对话为文本
    2. LLM 提取候选记忆
    3. 去重检查 + 重要性评分
    4. 达标记忆写入 Qdrant

    Args:
        user_id: 用户标识。
        langchain_messages: LangChain 消息列表。
    """
    from loguru import logger

    from agent.agent.fitness_agent import _create_llm  # noqa: PLC0415
    from agent.utils.config import config  # noqa: PLC0415

    try:
        # 1. 格式化对话
        conversation = format_conversation_for_extraction(langchain_messages)

        # 跳过太短的对话
        if len(conversation.strip()) < 50:
            logger.debug(f"Conversation too short for memory extraction (user={user_id})")
            return

        # 2. 创建 LLM（复用与 Agent 相同的配置）
        # 非流式：提取和评分都是一次性 ainvoke，不需要逐 token 输出
        llm = _create_llm(config, streaming=False)

        # 3. 提取候选记忆
        candidates = await extract_memories(
            conversation=conversation,
            llm=llm,
        )

        if not candidates:
            logger.debug(f"No memory candidates extracted for user={user_id}")
            return

        # 4. 获取已有记忆内容（用于去重上下文）
        store = MemoryStore(collection_name=config.memory_collection_name)
        existing = store.get_existing_content_list(user_id=user_id)

        # 5. 重要性评分
        scored = await score_importance(
            candidates=candidates,
            existing_memories=existing,
            llm=llm,
            threshold=config.memory_importance_threshold,
        )

        if not scored:
            logger.debug(f"No memories passed importance threshold for user={user_id}")
            return

        # 6. 去重 + 存储
        stored_count = 0
        stored_contents: set[str] = set()  # 批次内去重
        for memory in scored:
            # 跳过批次内重复的记忆（内容完全一致）
            if memory.content in stored_contents:
                logger.debug(f"Skipping intra-batch duplicate: {memory.content[:50]}...")
                continue

            # 跳过与已有记忆高度相似的
            is_dup = await store.dedup_check(
                content=memory.content,
                user_id=user_id,
            )
            if is_dup:
                logger.debug(f"Skipping duplicate memory: {memory.content[:50]}...")
                continue

            await store.add_memory(memory, user_id=user_id)
            stored_contents.add(memory.content)
            stored_count += 1

        logger.info(
            f"Memory extraction complete: user={user_id}, "
            f"candidates={len(candidates)}, scored={len(scored)}, stored={stored_count}"
        )

    except Exception:
        # fire-and-forget — silently log and continue
        logger.opt(exception=True).warning(
            f"Memory extraction failed for user={user_id}"
        )
