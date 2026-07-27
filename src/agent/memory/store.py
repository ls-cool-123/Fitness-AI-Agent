"""记忆向量存储。

管理 Qdrant 中 user_memories collection 的读写操作。
直接使用 Qdrant 客户端以支持 user_id 过滤和 payload 访问，
不经过 LangChain QdrantVectorStore 包装。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from langchain_core.embeddings import Embeddings
from loguru import logger
from qdrant_client.models import FieldCondition, Filter, MatchValue, PointStruct

from agent.memory.models import MemoryPayload, MemorySearchResult, ScoredMemory
from agent.utils.config import config
from agent.utils.embeddings import get_embedding_model
from agent.utils.vdb import initialize_vector_db, qdrant_client


def _get_embedding_model() -> Embeddings:
    """获取嵌入模型实例（带缓存）."""
    return get_embedding_model(config)


class MemoryStore:
    """用户长期记忆的向量存储。

    封装对 Qdrant user_memories collection 的读写操作：
    - 写入：将记忆文本向量化后存入 Qdrant
    - 搜索：按 user_id 过滤的语义检索
    - 去重：检查新记忆是否与已有记忆高度相似
    """

    def __init__(self, collection_name: str | None = None) -> None:
        self.collection_name = collection_name or config.memory_collection_name
        self._embedding = _get_embedding_model()

        # 确保 collection 存在
        initialize_vector_db(
            collection_name=self.collection_name,
            embeddings_size=config.embedding_size,
        )
        logger.info(f"MemoryStore initialized: collection={self.collection_name}")

    def _embed_content(self, content: str) -> list[float]:
        """将文本向量化，返回 float 列表。"""
        return self._embedding.embed_query(content)

    async def add_memory(self, memory: ScoredMemory, user_id: str) -> str:
        """嵌入并存储一条记忆。

        Args:
            memory: 经评分的记忆对象。
            user_id: 用户标识。

        Returns:
            Qdrant point ID 的字符串形式。
        """
        point_id = str(uuid.uuid4())
        vector = self._embed_content(memory.content)

        payload = MemoryPayload(
            user_id=user_id,
            content=memory.content,
            importance=memory.importance,
            timestamp=memory.timestamp.isoformat(),
            memory_type=memory.memory_type,
            category=memory.category,
        )

        qdrant_client.upsert(
            collection_name=self.collection_name,
            points=[
                PointStruct(
                    id=point_id,
                    vector=vector,
                    payload=payload.model_dump(),
                )
            ],
        )

        logger.debug(
            f"Memory stored: user={user_id}, type={memory.memory_type}, "
            f"importance={memory.importance:.2f}"
        )
        return point_id

    async def add_memories(
        self, memories: list[ScoredMemory], user_id: str
    ) -> list[str]:
        """批量存储记忆。

        Args:
            memories: 经评分的记忆列表。
            user_id: 用户标识。

        Returns:
            Qdrant point ID 列表。
        """
        return [await self.add_memory(m, user_id) for m in memories]

    def search_memories(
        self,
        query: str,
        user_id: str,
        top_k: int = 10,
    ) -> list[MemorySearchResult]:
        """按语义相似度检索用户记忆。

        使用 dense vector 检索，过滤条件为 user_id。
        这是 broad retrieval 阶段，不做 rerank 和时间衰减。

        Args:
            query: 查询文本。
            user_id: 用户标识（只检索该用户的记忆）。
            top_k: 返回的最大条数。

        Returns:
            按相似度降序排列的记忆搜索结果列表。
        """
        query_vector = self._embed_content(query)

        # 使用 user_id 过滤，只检索当前用户的记忆
        response = qdrant_client.query_points(
            collection_name=self.collection_name,
            query=query_vector,
            query_filter=Filter(
                must=[
                    FieldCondition(
                        key="user_id",
                        match=MatchValue(value=user_id),
                    )
                ]
            ),
            limit=top_k,
            with_payload=True,
        )

        return [
            MemorySearchResult(
                content=r.payload["content"],
                importance=r.payload["importance"],
                timestamp=r.payload["timestamp"],
                memory_type=r.payload["memory_type"],
                category=r.payload["category"],
                similarity_score=r.score,
            )
            for r in (response.points or [])
        ]

    async def dedup_check(
        self,
        content: str,
        user_id: str,
        threshold: float | None = None,
    ) -> bool:
        """检查是否已存在相似记忆。

        将新记忆 embedding 后去 Qdrant 搜同一用户的 top-1，
        若余弦相似度高于阈值则视为重复。

        Args:
            content: 候选记忆内容。
            user_id: 用户标识。
            threshold: 重复判定阈值，默认取配置值。

        Returns:
            True 表示已存在相似记忆（重复），False 表示为新记忆。
        """
        if threshold is None:
            threshold = 0.85  # 与 plan 中一致

        results = self.search_memories(
            query=content,
            user_id=user_id,
            top_k=1,
        )

        if not results:
            return False

        return results[0].similarity_score >= threshold

    def get_existing_content_list(self, user_id: str, limit: int = 50) -> list[str]:
        """获取用户已有记忆的内容列表（用于去重上下文）。

        使用 scroll API 获取最近 N 条记忆的 content 文本。

        Args:
            user_id: 用户标识。
            limit: 最大返回条数。

        Returns:
            记忆内容文本列表。
        """
        records, _ = qdrant_client.scroll(
            collection_name=self.collection_name,
            scroll_filter=Filter(
                must=[
                    FieldCondition(
                        key="user_id",
                        match=MatchValue(value=user_id),
                    )
                ]
            ),
            limit=limit,
            with_payload=["content"],
        )

        return [r.payload["content"] for r in records if r.payload and "content" in r.payload]
