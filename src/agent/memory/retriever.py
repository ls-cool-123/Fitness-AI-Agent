"""记忆检索器。

组合语义检索 + 重排序 + 时间衰减，返回最终的相关记忆榜单。

检索流程:
  1. Broad retrieval: MemoryStore.search_memories() → 粗筛 40 条
  2. Rerank: BGE CrossEncoder 精排，每条记忆获得 0-1 的 rerank_score
  3. Time decay: final_score = rerank_score × exp(-λ × days_elapsed)
  4. Sort & truncate: 按 final_score 降序取 top_k
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from langchain_core.documents import Document
from loguru import logger

from agent.memory.store import MemoryStore


class MemoryRetriever:
    """记忆检索 + 重排序 + 时间衰减。

    复用项目中已有的 BGE-reranker-v2-m3 进行精排，
    然后施加指数时间衰减，使旧记忆的相关性自然降低。
    """

    def __init__(
        self,
        memory_store: MemoryStore,
        broad_retrieval_k: int = 40,
        default_half_life_days: int = 30,
        half_life_by_type: dict[str, int] | None = None,
    ) -> None:
        """初始化记忆检索器。

        Args:
            memory_store: MemoryStore 实例。
            broad_retrieval_k: 粗检索阶段返回的最大记忆数。
            default_half_life_days: 默认半衰期（天）。
            half_life_by_type: 按记忆类型配置的半衰期映射。
        """
        self.store = memory_store
        self.broad_retrieval_k = broad_retrieval_k
        self.default_half_life = default_half_life_days
        self.half_life_by_type = half_life_by_type or {
            "user_goal": 60,
            "user_preference": 45,
            "training_insight": 30,
            "personal_info": 90,
            "conversation_summary": 14,
        }
        self._cross_encoder = None

    @property
    def cross_encoder(self):
        """延迟加载 BGE CrossEncoder（复用 reranker.py 中的缓存机制）."""
        if self._cross_encoder is None:
            from agent.utils.reranker import _get_bge_ranker  # noqa: PLC0415

            self._cross_encoder = _get_bge_ranker()
        return self._cross_encoder

    # ------------------------------------------------------------------
    # 时间衰减
    # ------------------------------------------------------------------

    @staticmethod
    def compute_decay(
        timestamp_str: str,
        half_life_days: int = 30,
        reference_time: datetime | None = None,
    ) -> float:
        """计算指数时间衰减因子。

        公式: decay = exp(-λ × days_elapsed)
        其中 λ = ln(2) / half_life_days

        Args:
            timestamp_str: ISO 8601 时间戳。
            half_life_days: 半衰期（天），表示经过这么天后衰减到 0.5。
            reference_time: 参考时间，默认当前 UTC。

        Returns:
            衰减因子，范围 (0, 1]。
        """
        if reference_time is None:
            reference_time = datetime.now(timezone.utc)

        memory_time = datetime.fromisoformat(timestamp_str)
        # 确保 memory_time 有 timezone 信息
        if memory_time.tzinfo is None:
            from datetime import timezone as tz

            memory_time = memory_time.replace(tzinfo=tz.utc)

        delta = reference_time - memory_time
        days_elapsed = max(delta.total_seconds() / 86400.0, 0.0)

        # λ = ln(2) / half_life
        lam = math.log(2) / half_life_days
        decay = math.exp(-lam * days_elapsed)

        return decay

    # ------------------------------------------------------------------
    # 重排序
    # ------------------------------------------------------------------

    def _rerank(
        self,
        query: str,
        contents: list[str],
    ) -> list[float]:
        """使用 BGE CrossEncoder 对 query-doc pairs 打分。

        Args:
            query: 查询文本。
            contents: 记忆内容列表。

        Returns:
            每条记忆的 rerank score 列表 (0-1 之间)。
        """
        pairs = [[query, content] for content in contents]
        scores = self.cross_encoder.predict(pairs, show_progress_bar=False)

        # 处理单条/批量返回
        if not hasattr(scores, "__iter__"):
            scores = [scores]

        # BGE CrossEncoder 输出范围大致在 -10 到 10，做 sigmoid 归一化到 (0,1)
        normalized = [1.0 / (1.0 + math.exp(-s)) for s in scores]
        return normalized

    # ------------------------------------------------------------------
    # 综合召回
    # ------------------------------------------------------------------

    async def recall(
        self,
        query: str,
        user_id: str,
        top_k: int = 5,
    ) -> list[dict]:
        """检索与该查询最相关的用户长期记忆。

        完整流程:
        1. Broad retrieval → 语义检索 40 条
        2. Rerank → BGE CrossEncoder 精排
        3. Time decay → 对 rerank_score 施加时间衰减
        4. Sort → 按 final_score 降序
        5. Truncate → 取 top_k

        Args:
            query: 查询文本（来自 Agent 的用户问题或子查询）。
            user_id: 用户标识。
            top_k: 最终返回的记忆条数。

        Returns:
            记忆字典列表，每条含 content, relevance, memory_type,
            category, timestamp, importance。
        """
        # Step 1: Broad retrieval
        broad_results = self.store.search_memories(
            query=query,
            user_id=user_id,
            top_k=self.broad_retrieval_k,
        )

        if not broad_results:
            logger.info(f"No memories found for user={user_id}")
            return []

        logger.debug(
            f"Broad retrieval: {len(broad_results)} memories for user={user_id}"
        )

        # Step 2: Rerank
        contents = [r.content for r in broad_results]
        rerank_scores = self._rerank(query, contents)

        # Step 3: Time decay + final score
        scored = []
        for result, rerank_score in zip(broad_results, rerank_scores):
            half_life = self.half_life_by_type.get(
                result.memory_type, self.default_half_life
            )
            decay = self.compute_decay(result.timestamp, half_life_days=half_life)
            final_score = rerank_score * decay

            scored.append({
                "content": result.content,
                "relevance": round(final_score, 4),
                "rerank_score": round(rerank_score, 4),
                "decay": round(decay, 4),
                "memory_type": result.memory_type,
                "category": result.category,
                "importance": result.importance,
                "timestamp": result.timestamp,
            })

        # Step 4: Sort by final_score descending
        scored.sort(key=lambda x: x["relevance"], reverse=True)

        # Step 5: Truncate to top_k
        top = scored[:top_k]

        logger.info(
            f"Memory recall: user={user_id}, query='{query[:50]}...', "
            f"broad={len(broad_results)}, top={len(top)}"
        )

        return top
