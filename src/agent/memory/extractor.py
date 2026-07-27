"""记忆提取器。

使用 LLM 从对话中提取候选记忆，并对其进行重要性评分。
只保留 score ≥ threshold 的记忆写入 Qdrant。

流程:
  1. extract_memories(): 从对话中提取候选记忆
  2. score_importance(): 对候选记忆评分，返回达标的记忆
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from loguru import logger

from agent.memory.models import MemoryCandidate, ScoredMemory

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

# ------------------------------------------------------------------
# Prompt: 记忆提取
# ------------------------------------------------------------------

EXTRACTION_SYSTEM_PROMPT = """你是一个健身助手的记忆提取模块。你的任务是从用户与健身助手的对话中，提取值得长期记住的信息。

## 提取规则
1. **只提取有长期价值的信息** — 用户的偏好、目标、个人数据、训练洞察
2. **忽略临时性/闲聊内容** — 问候、道别、纯询问天气/时间等
3. **每条记忆用一句话概括**，包含足够的上下文使其独立可理解。例如：
   - 好: "用户的目标是三个月内增肌5公斤，一周训练4天"
   - 差: "增肌5公斤"（缺少上下文）
4. **最多提取 5 条**，宁缺毋滥。如果对话中没有值得长期记忆的内容，返回空数组。

## 记忆分类
- `user_goal`: 用户的健身目标（增肌/减脂/力量/耐力等）
- `user_preference`: 用户的训练偏好（喜欢/不喜欢的动作、训练时间、教练风格等）
- `training_insight`: 从训练数据中发现的洞察（进步趋势、弱项、伤病等）
- `personal_info`: 用户的个人信息（年龄、体重、职业、日程等）
- `conversation_summary`: 对话的核心要点摘要

## 记忆分类
- `training`: 训练相关
- `nutrition`: 营养饮食
- `recovery`: 恢复休息
- `goals`: 目标
- `personal`: 个人信息

## 输出格式
返回 JSON 数组（不要包含 markdown 代码块标记），每条记忆包含 content、memory_type、category:
```json
[
  {"content": "用户偏好推类动作而非拉类动作，尤其喜欢卧推", "memory_type": "user_preference", "category": "training"},
  {"content": "用户的目标是三个月内体脂从20%降到15%", "memory_type": "user_goal", "category": "goals"}
]
```

如果无需记忆则返回空数组: []
"""

EXTRACTION_USER_TEMPLATE = """请从以下对话中提取值得长期记住的信息。

对话内容:
{conversation}

请输出 JSON 数组:"""

# ------------------------------------------------------------------
# Prompt: 重要性评分
# ------------------------------------------------------------------

SCORING_SYSTEM_PROMPT = """你是一个记忆重要性的评估模块。对每条候选记忆进行 0-1 打分。

## 评分维度
- **相关性** (0.35): 与健身训练/健康目标的相关程度。越是直接关联训练、饮食、健康，分数越高。
- **特异性** (0.25): 信息是否具体、可操作。含有具体数字、日期、动作名称的得分更高。
- **未来有用性** (0.25): 在未来的对话中可能被用到的概率。长期有用的目标 > 一次性的数据。
- **非冗余性** (0.15): 是否与已有记忆重复。如果已有记忆列表中有类似内容，降低分数。

## 评分标准
- 0.9-1.0: 极其重要 — 用户的核心目标和长期偏好
- 0.7-0.9: 重要 — 具体的训练偏好、明确的限制条件
- 0.5-0.7: 有一定价值 — 阶段性的观察或短期目标
- 0.3-0.5: 价值较低 — 模糊的偏好或可能不太准确的信息
- 0.0-0.3: 无长期价值 — 临时性或无关信息

## 输出格式
返回 JSON 数组（不要包含 markdown 代码块标记），每条包含 importance 和 reason:
```json
[
  {"importance": 0.85, "reason": "明确的三月期增肌目标，包含具体体重和时间，长期有用"},
  {"importance": 0.45, "reason": "偏好信息较模糊，缺少具体动作或理由"}
]
```
"""

SCORING_USER_TEMPLATE = """请对以下候选记忆进行重要性评分。

已有记忆（避免冗余）:
{existing_memories}

候选记忆:
{candidates}

请输出 JSON 数组（每条对应一条候选记忆）:"""


# ------------------------------------------------------------------
# 解析 JSON 的辅助函数
# ------------------------------------------------------------------

def _parse_json_array(text: str) -> list[dict]:
    """从 LLM 输出中解析 JSON 数组。

    处理 LLM 可能包裹 ```json ... ``` 或直接输出文本的情况。
    """
    # 尝试提取 ```json ... ``` 中的内容
    code_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if code_match:
        text = code_match.group(1)

    # 尝试找到第一个 [ 和最后一个 ]
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning(f"Failed to parse JSON from LLM output: {text[:200]}...")
        return []


# ------------------------------------------------------------------
# 主要函数
# ------------------------------------------------------------------


async def extract_memories(
    conversation: str,
    llm: BaseChatModel,
) -> list[MemoryCandidate]:
    """从对话文本中提取候选记忆。

    Args:
        conversation: 格式化的对话文本。
        llm: LLM 实例（与 Agent 共用）。

    Returns:
        候选记忆列表，可能为空。
    """
    messages = [
        SystemMessage(content=EXTRACTION_SYSTEM_PROMPT),
        HumanMessage(
            content=EXTRACTION_USER_TEMPLATE.format(conversation=conversation)
        ),
    ]

    response = await llm.ainvoke(messages)
    content = response.content if hasattr(response, "content") else str(response)
    raw_items = _parse_json_array(content)

    candidates = []
    for item in raw_items:
        try:
            candidates.append(MemoryCandidate(**item))
        except Exception:
            logger.warning(f"Skipping malformed memory candidate: {item}")

    logger.info(f"Extracted {len(candidates)} memory candidates")
    return candidates


async def score_importance(
    candidates: list[MemoryCandidate],
    existing_memories: list[str],
    llm: BaseChatModel,
    threshold: float = 0.6,
) -> list[ScoredMemory]:
    """对候选记忆进行重要性评分。

    Args:
        candidates: 候选记忆列表。
        existing_memories: 已有记忆内容列表（用于去重/降分）。
        llm: LLM 实例。
        threshold: 重要性阈值，低于此值的记忆被丢弃。

    Returns:
        通过阈值的 ScoredMemory 列表。
    """
    if not candidates:
        return []

    # 格式化候选记忆
    candidates_text = json.dumps(
        [
            {"index": i, "content": c.content, "memory_type": c.memory_type, "category": c.category}
            for i, c in enumerate(candidates)
        ],
        ensure_ascii=False,
        indent=2,
    )

    # 格式化已有记忆
    existing_text = "\n".join(f"- {m}" for m in existing_memories) if existing_memories else "（无已有记忆）"

    messages = [
        SystemMessage(content=SCORING_SYSTEM_PROMPT),
        HumanMessage(
            content=SCORING_USER_TEMPLATE.format(
                existing_memories=existing_text,
                candidates=candidates_text,
            )
        ),
    ]

    response = await llm.ainvoke(messages)
    content = response.content if hasattr(response, "content") else str(response)
    scores = _parse_json_array(content)

    scored = []
    for i, score_entry in enumerate(scores):
        if i >= len(candidates):
            break

        importance = float(score_entry.get("importance", 0))
        if importance >= threshold:
            candidate = candidates[i]
            scored.append(
                ScoredMemory(
                    content=candidate.content,
                    memory_type=candidate.memory_type,
                    category=candidate.category,
                    importance=importance,
                    importance_reason=score_entry.get("reason", ""),
                )
            )

    accepted = len(scored)
    rejected = len(candidates) - accepted
    logger.info(
        f"Importance scoring: {accepted} accepted, {rejected} rejected "
        f"(threshold={threshold})"
    )

    return scored


def format_conversation_for_extraction(
    messages: list,
    max_turns: int = 6,
) -> str:
    """将 LangChain 消息列表格式化为适合提取的文本。

    只取最近的 max_turns 轮对话（一轮 = 用户消息 + AI 回复），
    避免上下文过长。

    Args:
        messages: LangChain 消息列表 (HumanMessage / AIMessage)。
        max_turns: 最多保留的对话轮数。

    Returns:
        格式化的对话文本，如:
        User: 我想增肌
        Assistant: 好的！请问你现在的训练频率...
        User: 一周四天
        Assistant: ...
    """
    # 过滤掉 SystemMessage，只保留人类和 AI 的消息
    chat_messages = [m for m in messages if isinstance(m, (HumanMessage, AIMessage))]

    # 取最近 max_turns * 2 条消息（每轮有 User + Assistant 两条）
    recent = chat_messages[-(max_turns * 2):]

    lines = []
    for m in recent:
        role = "User" if isinstance(m, HumanMessage) else "Assistant"
        content = m.content if hasattr(m, "content") else str(m)
        # 截断过长的消息
        if len(content) > 500:
            content = content[:500] + "..."
        lines.append(f"{role}: {content}")

    return "\n".join(lines)
