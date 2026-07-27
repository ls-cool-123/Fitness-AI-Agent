"""记忆数据模型。

定义长期记忆系统中使用的 Pydantic 模型：
- MemoryCandidate : LLM 提取的候选记忆
- ScoredMemory : 经重要性评分后的记忆
- MemoryPayload : 写入 Qdrant 的 payload 结构
"""

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

MemoryType = Literal[
    "user_goal",
    "user_preference",
    "training_insight",
    "personal_info",
    "conversation_summary",
]

MemoryCategory = Literal[
    "training",
    "nutrition",
    "recovery",
    "goals",
    "personal",
]


class MemoryCandidate(BaseModel):
    """LLM 从对话中提取的原始候选记忆。"""

    content: str = Field(description="记忆内容，一句话概括，独立可理解")
    memory_type: MemoryType = Field(description="记忆类型")
    category: MemoryCategory = Field(description="记忆分类")


class ScoredMemory(MemoryCandidate):
    """经 LLM 重要性评分后的记忆，附带评分和时间戳。"""

    importance: float = Field(ge=0.0, le=1.0, description="重要性评分 0-1")
    importance_reason: str = Field(default="", description="评分理由")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="记忆创建时间 (UTC)",
    )


class MemoryPayload(BaseModel):
    """写入 Qdrant point 的 payload 结构。

    Qdrant 中每个 point 的向量是 content 的 embedding，
    payload 包含以下元数据用于过滤和衰减计算。
    """

    user_id: str = Field(description="用户标识")
    content: str = Field(description="记忆内容")
    importance: float = Field(description="重要性评分 0-1")
    timestamp: str = Field(description="ISO 8601 格式的创建时间")
    memory_type: str = Field(description="记忆类型")
    category: str = Field(description="记忆分类")


class MemorySearchResult(BaseModel):
    """从 Qdrant 检索到的单条记忆结果。"""

    content: str
    importance: float
    timestamp: str
    memory_type: str
    category: str
    similarity_score: float = Field(description="Qdrant 返回的原始相似度分数")
