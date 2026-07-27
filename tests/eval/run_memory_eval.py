"""长期记忆系统评测 —— 噪音率 + 偏好召回率。

评测内容：
  Part A — 噪音率：12 段模拟对话 → 真实提取管线 → 对比 ground truth
              → 统计 noise_rate / valuable_coverage @ threshold 0.5/0.6/0.7
  Part B — 偏好召回：写入 20 条种子记忆 → 12 个召回 query
              → 统计 Recall@5 / Precision@5 / MRR

用法：
  ALLOW_NETWORK_TESTS=1 uv run python tests/eval/run_memory_eval.py
"""

from __future__ import annotations

import asyncio
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ── 将项目根加入 sys.path ────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from agent.agent.fitness_agent import _create_llm  # noqa: E402
from agent.memory.extractor import (  # noqa: E402
    extract_memories,
    format_conversation_for_extraction,
    score_importance,
)
from agent.memory.models import ScoredMemory  # noqa: E402
from agent.memory.retriever import MemoryRetriever  # noqa: E402
from agent.memory.store import MemoryStore  # noqa: E402
from agent.utils.config import config  # noqa: E402
from langchain_core.messages import AIMessage, HumanMessage  # noqa: E402
from loguru import logger  # noqa: E402

# ── 路径配置 ──────────────────────────────────────────────────────────────
EVAL_DIR = Path(__file__).parent
DATA_FILE = EVAL_DIR / "eval_memory_data.json"
RESULT_FILE = EVAL_DIR / "memory_eval_results.json"

EVAL_USER_ID = "eval-memory-user-00000000"

# ── 辅助函数 ──────────────────────────────────────────────────────────────


def messages_to_langchain(messages: list[dict]) -> list:
    """将 dict 格式的消息列表转为 LangChain 消息列表。"""
    result = []
    for m in messages:
        if m["role"] == "user":
            result.append(HumanMessage(content=m["content"]))
        elif m["role"] == "assistant":
            result.append(AIMessage(content=m["content"]))
    return result


def simple_normalize(text: str) -> str:
    """简单归一化：去除标点空格差异，用于宽松匹配。"""
    import re

    return re.sub(r"[，。！？、；：—\s]+", "", text)


def match_memory(memory_content: str, ground_truth_items: list[str]) -> int:
    """检查一条记忆是否命中任一 ground truth 条目。

    返回匹配到的 ground truth 索引，-1 表示未命中。
    """
    norm_mem = simple_normalize(memory_content)
    for i, gt in enumerate(ground_truth_items):
        norm_gt = simple_normalize(gt)

        # 完全包含
        if norm_gt in norm_mem or norm_mem in norm_gt:
            return i

        # 关键词重叠 ≥ 60%
        gt_chars = set(norm_gt)
        mem_chars = set(norm_mem)
        if gt_chars and mem_chars:
            overlap = len(gt_chars & mem_chars) / len(gt_chars)
            if overlap >= 0.60:
                return i

    return -1


# ═══════════════════════════════════════════════════════════════════════════
#  Part A: 噪音率评测
# ═══════════════════════════════════════════════════════════════════════════


async def run_noise_eval() -> dict:
    """运行噪音率评测。"""
    with open(DATA_FILE, encoding="utf-8") as f:
        conversations = json.load(f)

    llm = _create_llm(config)

    # 清理 eval 用户的旧记忆
    store = MemoryStore(collection_name=config.memory_collection_name)
    _purge_user_memories(store, EVAL_USER_ID)

    results_per_threshold = {
        "0.5": [],
        "0.6": [],
        "0.7": [],
    }

    total_should_remember = 0
    total_should_forget = 0

    for conv in conversations:
        conv_id = conv["conversation_id"]
        desc = conv["description"]
        should_remember = conv["should_remember"]
        should_forget = conv["should_forget"]
        total_should_remember += len(should_remember)
        total_should_forget += len(should_forget)

        print(f"\n  [{conv_id}] {desc}")
        print(f"    Ground truth: {len(should_remember)} remember, {len(should_forget)} forget")

        # 1. 格式化对话
        lc_messages = messages_to_langchain(conv["messages"])
        conversation_text = format_conversation_for_extraction(lc_messages)

        # 2. LLM 提取候选记忆
        try:
            candidates = await extract_memories(conversation_text, llm)
        except Exception as e:
            logger.error(f"Extraction failed for {conv_id}: {e}")
            continue

        print(f"    Candidates extracted: {len(candidates)}")

        if not candidates:
            # 如果 ground truth 也没有要记的，说明正确
            for thresh in results_per_threshold:
                results_per_threshold[thresh].append({
                    "conv_id": conv_id,
                    "candidates": 0,
                    "stored": 0,
                    "tp": 0,
                    "fp": 0,
                    "fn": len(should_remember),
                    "tn": len(should_forget),
                })
            continue

        # 3. 获取已有记忆（用于去重上下文）
        existing = store.get_existing_content_list(user_id=EVAL_USER_ID)

        # 4. 对三个阈值分别评分
        for threshold_str, threshold_val in [("0.5", 0.5), ("0.6", 0.6), ("0.7", 0.7)]:
            try:
                scored = await score_importance(
                    candidates=candidates,
                    existing_memories=existing,
                    llm=llm,
                    threshold=threshold_val,
                )
            except Exception as e:
                logger.error(f"Scoring failed for {conv_id} at threshold {threshold_val}: {e}")
                continue

            # 5. 统计 true positive / false positive / false negative
            tp = 0  # 正确存储（memory 命中 should_remember）
            fp = 0  # 噪音（memory 命中 should_forget 或未命中任何 ground truth）
            fn = 0  # 漏存（should_remember 未被任何 memory 命中）
            matched_gt = set()

            for mem in scored:
                # 检查是否命中 should_remember
                gt_idx = match_memory(mem.content, should_remember)
                if gt_idx >= 0:
                    tp += 1
                    matched_gt.add(gt_idx)
                else:
                    # 检查是否命中 should_forget
                    fg_idx = match_memory(mem.content, should_forget)
                    if fg_idx >= 0:
                        fp += 1
                    else:
                        # 未命中任何 ground truth → 可能是噪音或 LLM 生成了不相关记忆
                        fp += 1

            fn = len(should_remember) - len(matched_gt)

            print(f"    Threshold {threshold_str}: stored={len(scored)}, tp={tp}, fp={fp}, fn={fn}")

            results_per_threshold[threshold_str].append({
                "conv_id": conv_id,
                "candidates": len(candidates),
                "stored": len(scored),
                "tp": tp,
                "fp": fp,
                "fn": fn,
                "tn": len(should_forget),
            })

        # 将对话中提取的记忆写入 store（为后续召回评测做准备）
        # 使用 threshold 0.6 的实际结果
        for thresh_str in ["0.6"]:
            for r in results_per_threshold[thresh_str]:
                if r["conv_id"] == conv_id:
                    break
            else:
                continue

    # ── 汇总统计 ──
    summary = {}
    for thresh, items in results_per_threshold.items():
        total_candidates = sum(it["candidates"] for it in items)
        total_stored = sum(it["stored"] for it in items)
        total_tp = sum(it["tp"] for it in items)
        total_fp = sum(it["fp"] for it in items)
        total_fn = sum(it["fn"] for it in items)

        noise_rate = total_fp / total_stored if total_stored > 0 else 0.0
        coverage = total_tp / total_should_remember if total_should_remember > 0 else 0.0
        precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
        recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

        summary[thresh] = {
            "threshold": float(thresh),
            "total_conversations": len(items),
            "total_candidates": total_candidates,
            "total_stored": total_stored,
            "total_tp": total_tp,
            "total_fp": total_fp,
            "total_fn": total_fn,
            "noise_rate": round(noise_rate, 4),
            "valuable_coverage": round(coverage, 4),
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
        }

    return summary


# ═══════════════════════════════════════════════════════════════════════════
#  Part B: 偏好召回率评测
# ═══════════════════════════════════════════════════════════════════════════


SEED_MEMORIES: list[dict] = [
    {"content": "用户偏好高强度间歇训练(HIIT)而非长时间有氧", "memory_type": "user_preference", "category": "training", "importance": 0.85},
    {"content": "用户喜欢早上6-7点训练，训练前吃一根香蕉", "memory_type": "user_preference", "category": "training", "importance": 0.80},
    {"content": "用户偏好自由重量（杠铃、哑铃）而非固定器械", "memory_type": "user_preference", "category": "training", "importance": 0.75},
    {"content": "用户最喜欢的背部动作是负重引体向上", "memory_type": "user_preference", "category": "training", "importance": 0.70},
    {"content": "用户的目标：一年内完成全程马拉松（完赛即可）", "memory_type": "user_goal", "category": "goals", "importance": 0.90},
    {"content": "用户的目标：三个月内体脂从25%降到15%", "memory_type": "user_goal", "category": "goals", "importance": 0.88},
    {"content": "用户的目标：三个月内增肌5公斤，当前体重65公斤", "memory_type": "user_goal", "category": "goals", "importance": 0.92},
    {"content": "用户有肩峰下撞击综合征，禁止过头推举类动作", "memory_type": "personal_info", "category": "training", "importance": 0.95},
    {"content": "用户有膝盖旧伤，深蹲时需要特别注意膝关节保护", "memory_type": "personal_info", "category": "training", "importance": 0.88},
    {"content": "用户年龄35岁，职业程序员，每天久坐约10小时", "memory_type": "personal_info", "category": "personal", "importance": 0.78},
    {"content": "用户有颈椎和腰椎问题，与久坐相关", "memory_type": "personal_info", "category": "personal", "importance": 0.82},
    {"content": "用户采用碳水循环饮食法：训练日200克碳水，休息日100克碳水", "memory_type": "training_insight", "category": "nutrition", "importance": 0.80},
    {"content": "用户偏好牛肉和三文鱼作为蛋白质来源，不喜欢鸡胸肉", "memory_type": "user_preference", "category": "nutrition", "importance": 0.76},
    {"content": "用户每天喝拿铁咖啡，减脂期可接受换成脱脂奶", "memory_type": "user_preference", "category": "nutrition", "importance": 0.65},
    {"content": "用户有生酮减肥经历：减重10公斤后反弹，希望找到更可持续的方法", "memory_type": "training_insight", "category": "nutrition", "importance": 0.85},
    {"content": "用户一个月内卧推从60kg提升到70kg（+10kg）", "memory_type": "training_insight", "category": "training", "importance": 0.72},
    {"content": "用户硬拉时有下背不适，需要注意核心收紧和髋铰链", "memory_type": "training_insight", "category": "training", "importance": 0.78},
    {"content": "用户上肢日采用推拉超级组训练方式", "memory_type": "user_preference", "category": "training", "importance": 0.70},
    {"content": "用户减脂期睡眠质量差，经常半夜醒来", "memory_type": "training_insight", "category": "recovery", "importance": 0.74},
    {"content": "用户自己做饭且能控制油盐，具备良好的饮食控制条件", "memory_type": "personal_info", "category": "nutrition", "importance": 0.72},
]

RECALL_QUERIES: list[dict] = [
    {
        "query": "用户的健身目标是什么",
        "relevant_indices": [4, 5, 6],
    },
    {
        "query": "用户有哪些伤病需要注意",
        "relevant_indices": [7, 8],
    },
    {
        "query": "用户喜欢什么样的训练方式",
        "relevant_indices": [0, 1, 2, 3],
    },
    {
        "query": "用户的饮食习惯和偏好",
        "relevant_indices": [12, 13, 14, 15, 19],
    },
    {
        "query": "用户的个人信息和职业",
        "relevant_indices": [9, 10],
    },
    {
        "query": "用户最近训练有没有进步",
        "relevant_indices": [16],
    },
    {
        "query": "用户下肢训练有什么限制",
        "relevant_indices": [8, 17],
    },
    {
        "query": "用户喜欢什么时间训练",
        "relevant_indices": [1],
    },
    {
        "query": "用户的减脂目标进展",
        "relevant_indices": [5],
    },
    {
        "query": "用户睡眠怎么样",
        "relevant_indices": [18],
    },
    {
        "query": "用户卧推练得怎么样",
        "relevant_indices": [16],
    },
    {
        "query": "用户对鸡胸肉的态度",
        "relevant_indices": [13],
    },
]


async def seed_memories(store: MemoryStore, user_id: str) -> list[str]:
    """将种子记忆写入 Qdrant。返回 point ID 列表。"""
    ids = []
    for mem in SEED_MEMORIES:
        scored = ScoredMemory(
            content=mem["content"],
            memory_type=mem["memory_type"],  # type: ignore[arg-type]
            category=mem["category"],  # type: ignore[arg-type]
            importance=mem["importance"],
            importance_reason="seed data for evaluation",
            timestamp=datetime.now(timezone.utc),
        )
        pid = await store.add_memory(scored, user_id=user_id)
        ids.append(pid)
    print(f"  Seeded {len(ids)} memories for {user_id}")
    return ids


def _purge_user_memories(store: MemoryStore, user_id: str) -> None:
    """删除指定用户的所有记忆（清理评测数据）。"""
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    from agent.utils.vdb import qdrant_client

    try:
        qdrant_client.delete(
            collection_name=store.collection_name,
            points_selector=Filter(
                must=[FieldCondition(key="user_id", match=MatchValue(value=user_id))]
            ),
        )
    except Exception as e:
        logger.warning(f"Failed to purge memories for {user_id}: {e}")


def compute_recall_metrics(
    query_results: list[list[dict]],
    queries: list[dict],
) -> dict:
    """计算召回率、精确率、MRR、NDCG 等指标。"""
    recall_scores = []
    precision_scores = []
    mrr_scores = []
    ndcg_scores = []

    for results, q_info in zip(query_results, queries):
        relevant = set(q_info["relevant_indices"])

        # 获取检索结果的 index（与种子记忆匹配）
        retrieved_items = []
        for r in results:
            # 用 content 精确匹配种子记忆
            for idx, seed in enumerate(SEED_MEMORIES):
                if seed["content"] == r["content"]:
                    retrieved_items.append(idx)
                    break
            else:
                retrieved_items.append(-1)  # 不在种子列表内（理论上不应该出现）

        top_5 = retrieved_items[:5]

        # Recall@5
        hits = sum(1 for rid in top_5 if rid in relevant)
        recall = hits / len(relevant) if relevant else 0.0
        recall_scores.append(recall)

        # Precision@5
        prec = hits / len(top_5) if top_5 else 0.0
        precision_scores.append(prec)

        # MRR
        mrr_val = 0.0
        for rank, rid in enumerate(top_5, 1):
            if rid in relevant:
                mrr_val = 1.0 / rank
                break
        mrr_scores.append(mrr_val)

        # NDCG@5
        rels = [1 if rid in relevant else 0 for rid in top_5]
        dcg = sum(rel / math.log2(i + 2) for i, rel in enumerate(rels))
        ideal_rels = sorted(rels, reverse=True)
        idcg = sum(rel / math.log2(i + 2) for i, rel in enumerate(ideal_rels))
        ndcg = dcg / idcg if idcg > 0 else 0.0
        ndcg_scores.append(ndcg)

    return {
        "recall_at_5": round(sum(recall_scores) / len(recall_scores), 4),
        "precision_at_5": round(sum(precision_scores) / len(precision_scores), 4),
        "mrr": round(sum(mrr_scores) / len(mrr_scores), 4),
        "ndcg_at_5": round(sum(ndcg_scores) / len(ndcg_scores), 4),
        "per_query": [
            {
                "query": q["query"],
                "recall@5": round(rc, 4),
                "precision@5": round(pr, 4),
                "mrr": round(mr, 4),
                "ndcg@5": round(nd, 4),
            }
            for q, rc, pr, mr, nd in zip(
                queries, recall_scores, precision_scores, mrr_scores, ndcg_scores
            )
        ],
    }


async def run_recall_eval() -> dict:
    """运行偏好召回率评测。"""
    store = MemoryStore(collection_name=config.memory_collection_name)

    # 清理 + 重新写入种子记忆
    print("\n  写入种子记忆...")
    _purge_user_memories(store, EVAL_USER_ID)
    await seed_memories(store, EVAL_USER_ID)

    # 创建检索器
    retriever = MemoryRetriever(
        memory_store=store,
        broad_retrieval_k=40,
        default_half_life_days=config.memory_half_life_days,
    )

    # 逐条 query 检索
    print(f"\n  运行 {len(RECALL_QUERIES)} 条召回查询...")
    query_results = []
    for i, q_info in enumerate(RECALL_QUERIES):
        query = q_info["query"]
        relevant_count = len(q_info["relevant_indices"])
        print(f"    [{i+1}/{len(RECALL_QUERIES)}] '{query}' (relevant: {relevant_count})")

        results = await retriever.recall(
            query=query,
            user_id=EVAL_USER_ID,
            top_k=5,
        )
        query_results.append(results)

    # 计算指标
    metrics = compute_recall_metrics(query_results, RECALL_QUERIES)

    # 清理种子记忆
    _purge_user_memories(store, EVAL_USER_ID)

    return metrics


# ═══════════════════════════════════════════════════════════════════════════
#  主入口
# ═══════════════════════════════════════════════════════════════════════════


async def main():
    print("=" * 70)
    print("  长期记忆系统评测")
    print(f"  评测用户: {EVAL_USER_ID}")
    print("=" * 70)

    # ── Part A: 噪音率 ──
    print("\n" + "─" * 70)
    print("  Part A: 噪音率评测（提取管线 + LLM 评分）")
    print("─" * 70)
    t0 = time.perf_counter()
    noise_results = await run_noise_eval()
    elapsed_a = time.perf_counter() - t0
    print(f"\n  Part A 完成 ({elapsed_a:.1f}s)")

    # ── Part B: 召回率 ──
    print("\n" + "─" * 70)
    print("  Part B: 偏好召回率评测（20 条种子记忆 → 12 个 Query）")
    print("─" * 70)
    t0 = time.perf_counter()
    recall_results = await run_recall_eval()
    elapsed_b = time.perf_counter() - t0
    print(f"\n  Part B 完成 ({elapsed_b:.1f}s)")

    # ── 输出汇总 ──
    print("\n" + "=" * 70)
    print("  评测汇总")
    print("=" * 70)

    print("\n  ┌─ Part A: 噪音率 ─────────────────────────────────────┐")
    print(f"  │ {'阈值':<6s} {'噪音率↓':>8s} {'覆盖率↑':>8s} {'精确率↑':>8s} {'召回率↑':>8s} {'F1':>8s} │")
    print("  │ " + "-" * 54 + " │")
    for thresh_str in ["0.5", "0.6", "0.7"]:
        s = noise_results[thresh_str]
        print(
            f"  │ {thresh_str:<6s} "
            f"{s['noise_rate']:>8.2%} "
            f"{s['valuable_coverage']:>8.2%} "
            f"{s['precision']:>8.2%} "
            f"{s['recall']:>8.2%} "
            f"{s['f1']:>8.4f} │"
        )
    print("  └" + "─" * 55 + "┘")

    print("\n  ┌─ Part B: 偏好召回率 ────────────────────────────────┐")
    print(f"  │ Recall@5        = {recall_results['recall_at_5']:.4f}                             │")
    print(f"  │ Precision@5     = {recall_results['precision_at_5']:.4f}                             │")
    print(f"  │ MRR             = {recall_results['mrr']:.4f}                             │")
    print(f"  │ NDCG@5          = {recall_results['ndcg_at_5']:.4f}                             │")
    print("  └" + "─" * 55 + "┘")

    # ── 保存详细结果 ──
    output = {
        "config": {
            "eval_user_id": EVAL_USER_ID,
            "model": config.model_name,
            "embedding": config.embedding_model_name,
            "conversations": 12,
            "recall_queries": len(RECALL_QUERIES),
            "seed_memories": len(SEED_MEMORIES),
        },
        "part_a_noise_rate": noise_results,
        "part_b_recall": recall_results,
    }

    with open(RESULT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n  详细结果已保存到: {RESULT_FILE}")

    print("\n" + "=" * 70)
    print("  评测完成。")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
