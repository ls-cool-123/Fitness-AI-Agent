"""RAG 搜索工具 —— 仅负责检索 + 重排序，不生成最终回答。

从 Qdrant 向量库中检索相关文档片段，由 Fitness Agent 的 LLM
负责基于这些片段合成最终答案。
"""

from __future__ import annotations

import json

from langchain_core.tools import tool
from loguru import logger

from agent.utils.config import config
from agent.utils.retriever import get_retriever


@tool
async def rag_search_tool(
    query: str,
    collection_name: str = "fitness_kb",
    top_k: int = 5,
) -> str:
    """搜索健身知识库，获取相关信息。

    当用户询问以下内容时使用此工具：
    - 运动理论、正确姿势或技巧
    - 训练计划、周期化训练或编程
    - 营养、饮食或补剂
    - 恢复、伤病预防或活动度
    - 运动科学或运动生理学

    此工具返回相关文档片段。请勿用它来记录训练、查询个人训练历史或**生成
    具体训练计划**：记录训练用 add_workout_tool，查询历史用 query_workout_tool，
    生成个人计划用 create_training_plan_tool。只有当用户问的是训练计划的
    理论/原理（如"周期化训练为什么有效"）时才用本工具。

    Args:
        query: 要搜索的具体问题。
        collection_name: Qdrant 集合名称（默认 "fitness_kb"）。
        top_k: 返回的文档片段数量（默认 5）。

    Returns:
        包含相关文档片段及元数据的 JSON 字符串。
    """
    try:
        # 粗筛阶段：多拉候选文档（默认 40 条），充分发挥混合检索的召回优势
        # 稠密向量覆盖语义相关，BM25 覆盖关键词匹配，两者互补
        retriever = get_retriever(k=config.retrieval_k, collection_name=collection_name)
        docs = await retriever.ainvoke(query)

        # 精排阶段：用 BGE/FlashRank 对粗筛结果重排序，返回 (docs, scores)
        if config.rerank_provider != "none":
            # 只把前 N 条交给 Cross-Encoder：CPU 上重排 40 条要 30 秒以上，
            # 而粗筛 16~40 名很少能翻盘，把候选压到 15 条是延迟与效果的折中
            candidates = docs[: config.rerank_candidates]
            from agent.utils.reranker import get_reranker
            reranker = get_reranker(
                provider=config.rerank_provider,
                top_k=min(top_k, len(candidates)),
            )
            docs, scores = reranker(candidates, query)

            # 阈值过滤：丢弃低于阈值的 chunk，防止 LLM 基于低质量文本编造回答
            threshold = config.rerank_score_threshold
            if threshold > 0:
                filtered = [(doc, s) for doc, s in zip(docs, scores) if s >= threshold]
                if not filtered:
                    logger.info(
                        f"All {len(docs)} chunks below threshold {threshold}, "
                        f"max_score={max(scores):.4f}"
                    )
                    return json.dumps({
                        "status": "no_relevant_info",
                        "message": (
                            "知识库中暂无与该问题高度相关的信息，"
                            "建议联系人工客服获取更准确的答案。"
                        ),
                        "max_score": round(max(scores), 4),
                        "threshold": threshold,
                    }, ensure_ascii=False)
                docs = [doc for doc, _ in filtered]
                scores = [s for _, s in filtered]
        else:
            # 未启用重排序时直接截断，无分数
            docs = docs[:top_k]
            scores = [1.0] * len(docs)

        # 格式化结果 —— 返回内容 + 元数据 + 重排序分数
        results = []
        for i, doc in enumerate(docs):
            source = doc.metadata.get("source", "unknown")
            category = doc.metadata.get("category", "general")
            results.append({
                "index": i + 1,
                "content": doc.page_content,
                "source": source,
                "category": category,
                "score": round(scores[i], 4) if i < len(scores) else None,
            })

        logger.info(f"RAG search returned {len(results)} chunks for query: {query[:60]}")
        return json.dumps(results, ensure_ascii=False, indent=2)

    except Exception as e:
        logger.error(f"RAG search failed: {e}")
        return json.dumps({"error": f"Search failed: {e}"}, ensure_ascii=False)
