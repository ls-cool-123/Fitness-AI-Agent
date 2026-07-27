"""Part B: 偏好召回率评测 — 独立脚本。

用法：
  ALLOW_NETWORK_TESTS=1 uv run python tests/eval/run_recall_eval.py
"""

from __future__ import annotations

import asyncio
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from agent.memory.models import ScoredMemory
from agent.memory.retriever import MemoryRetriever
from agent.memory.store import MemoryStore
from agent.utils.config import config
from qdrant_client.models import FieldCondition, Filter, MatchValue
from agent.utils.vdb import qdrant_client as qc

EVAL_USER_ID = "eval-memory-user-00000000"
RESULT_FILE = Path(__file__).parent / "memory_eval_recall_results.json"

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
    {"query": "用户的健身目标是什么", "relevant_indices": [4, 5, 6]},
    {"query": "用户有哪些伤病需要注意", "relevant_indices": [7, 8]},
    {"query": "用户喜欢什么样的训练方式", "relevant_indices": [0, 1, 2, 3]},
    {"query": "用户的饮食习惯和偏好", "relevant_indices": [12, 13, 14, 15, 19]},
    {"query": "用户的个人信息和职业", "relevant_indices": [9, 10]},
    {"query": "用户最近训练有没有进步", "relevant_indices": [16]},
    {"query": "用户下肢训练有什么限制", "relevant_indices": [8, 17]},
    {"query": "用户喜欢什么时间训练", "relevant_indices": [1]},
    {"query": "用户减脂目标进展", "relevant_indices": [5]},
    {"query": "用户睡眠怎么样", "relevant_indices": [18]},
    {"query": "用户卧推练得怎么样", "relevant_indices": [16]},
    {"query": "用户对鸡胸肉的态度", "relevant_indices": [13]},
]


async def main():
    store = MemoryStore(collection_name=config.memory_collection_name)

    # Purge old eval data
    print("Purging old eval memories...")
    try:
        qc.delete(
            collection_name=store.collection_name,
            points_selector=Filter(
                must=[FieldCondition(key="user_id", match=MatchValue(value=EVAL_USER_ID))]
            ),
        )
    except Exception as e:
        print(f"  Purge note: {e}")

    # Seed memories
    print("Seeding 20 memories...")
    for mem in SEED_MEMORIES:
        scored = ScoredMemory(
            content=mem["content"],
            memory_type=mem["memory_type"],  # type: ignore[arg-type]
            category=mem["category"],  # type: ignore[arg-type]
            importance=mem["importance"],
            importance_reason="seed data",
            timestamp=datetime.now(timezone.utc),
        )
        await store.add_memory(scored, user_id=EVAL_USER_ID)
    print("Seed done.")

    # Create retriever with default half-life (30d → all decay ≈ 1.0 for fresh memories)
    retriever = MemoryRetriever(
        memory_store=store,
        broad_retrieval_k=40,
        default_half_life_days=config.memory_half_life_days,
    )

    recall_scores, prec_scores, mrr_scores, ndcg_scores = [], [], [], []
    per_query = []

    print(f"\nRunning {len(RECALL_QUERIES)} queries...")
    for i, q_info in enumerate(RECALL_QUERIES):
        query = q_info["query"]
        relevant = set(q_info["relevant_indices"])
        results = await retriever.recall(query=query, user_id=EVAL_USER_ID, top_k=5)

        # Match results to seed indices by content exact match
        retrieved_indices = []
        for r in results:
            for idx, seed in enumerate(SEED_MEMORIES):
                if seed["content"] == r["content"]:
                    retrieved_indices.append(idx)
                    break
            else:
                retrieved_indices.append(-1)

        top5 = retrieved_indices[:5]
        hits = sum(1 for rid in top5 if rid in relevant)
        recall = hits / len(relevant) if relevant else 0.0
        prec = hits / len(top5) if top5 else 0.0

        mrr_val = 0.0
        for rank, rid in enumerate(top5, 1):
            if rid in relevant:
                mrr_val = 1.0 / rank
                break

        rels = [1 if rid in relevant else 0 for rid in top5]
        dcg = sum(rel / math.log2(j + 2) for j, rel in enumerate(rels))
        ideal_rels = sorted(rels, reverse=True)
        idcg = sum(rel / math.log2(j + 2) for j, rel in enumerate(ideal_rels))
        ndcg = dcg / idcg if idcg > 0 else 0.0

        recall_scores.append(recall)
        prec_scores.append(prec)
        mrr_scores.append(mrr_val)
        ndcg_scores.append(ndcg)

        print(f"  [{i+1:2d}/12] \"{query}\" -> "
              f"recall@5={recall:.2f} prec@5={prec:.2f} mrr={mrr_val:.2f} ndcg={ndcg:.2f} "
              f"hits: {retrieved_indices[:5]}")

        per_query.append({
            "query": query,
            "relevant_count": len(relevant),
            "retrieved_indices": retrieved_indices[:5],
            "recall_at_5": round(recall, 4),
            "precision_at_5": round(prec, 4),
            "mrr": round(mrr_val, 4),
            "ndcg_at_5": round(ndcg, 4),
        })

    avg_recall = sum(recall_scores) / len(recall_scores)
    avg_prec = sum(prec_scores) / len(prec_scores)
    avg_mrr = sum(mrr_scores) / len(mrr_scores)
    avg_ndcg = sum(ndcg_scores) / len(ndcg_scores)

    print(f"\n{'='*60}")
    print(f"  Part B — 偏好召回率 汇总:")
    print(f"  Recall@5    = {avg_recall:.4f}")
    print(f"  Precision@5 = {avg_prec:.4f}")
    print(f"  MRR         = {avg_mrr:.4f}")
    print(f"  NDCG@5      = {avg_ndcg:.4f}")
    print(f"{'='*60}")

    # Save results
    output = {
        "summary": {
            "recall_at_5": round(avg_recall, 4),
            "precision_at_5": round(avg_prec, 4),
            "mrr": round(avg_mrr, 4),
            "ndcg_at_5": round(avg_ndcg, 4),
        },
        "per_query": per_query,
    }
    with open(RESULT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\nResults saved to: {RESULT_FILE}")

    # Cleanup
    print("Cleaning up seed memories...")
    try:
        qc.delete(
            collection_name=store.collection_name,
            points_selector=Filter(
                must=[FieldCondition(key="user_id", match=MatchValue(value=EVAL_USER_ID))]
            ),
        )
    except Exception as e:
        print(f"  Cleanup note: {e}")
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
