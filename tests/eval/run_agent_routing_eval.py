"""ReAct Agent 工具路由准确率评测。

对每条 query 调用 Agent，通过 astream_events 捕获实际调用的工具，
与预期工具列表对比，计算准确率。

用法：
  uv run python tests/eval/run_agent_routing_eval.py
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from agent.agent.fitness_agent import fitness_agent
from agent.tools import current_user_id

EVAL_FILE = Path(__file__).parent / "eval_agent_queries.json"
TEST_USER = "default-user"


def _safe(s: str) -> str:
    """过滤 Windows GBK 终端无法显示的字符。"""
    return s.encode("gbk", errors="replace").decode("gbk")


async def run_one_query(query: str, user_id: str) -> tuple[list[str], str]:
    """运行 Agent 并捕获其调用的工具列表。"""
    tools_called: list[str] = []
    final_answer = ""

    config = {"configurable": {"thread_id": f"eval-{user_id}-{time.time()}"}}

    token = current_user_id.set(user_id)
    try:
        async for event in fitness_agent.astream_events(
            {"messages": [{"role": "user", "content": query}]},
            config=config,
            version="v2",
        ):
            kind = event["event"]
            if kind == "on_tool_start":
                tools_called.append(event.get("name", "unknown"))
            elif kind == "on_chat_model_stream":
                content = event["data"]["chunk"].content
                if content:
                    final_answer += content
    finally:
        current_user_id.reset(token)

    return tools_called, final_answer


async def main():
    with open(EVAL_FILE, encoding="utf-8") as f:
        queries = json.load(f)

    total = len(queries)
    correct = 0
    partial = 0
    false_positive = 0
    false_negative = 0
    results: list[dict] = []

    print(f"Agent 工具路由评测 — {total} 条 query, 用户: {TEST_USER}")
    print("=" * 80)

    for i, item in enumerate(queries):
        query = item["query"]
        expected = set(item["expected_tools"])

        print(f"\n[{i+1}/{total}] {_safe(query)}")
        print(f"  预期工具: {expected if expected else '(无需调工具)'}")

        t0 = time.perf_counter()
        actual_tools, answer = await run_one_query(query, TEST_USER)
        elapsed = time.perf_counter() - t0

        actual_set = set(actual_tools)
        print(f"  实际调用: {actual_set if actual_set else '(未调任何工具)'}")
        print(f"  回答摘要: {_safe(answer[:100])}...")
        print(f"  耗时: {elapsed:.1f}s")

        # 判断正确性
        if expected == actual_set:
            verdict = "OK"
            correct += 1
        elif expected and not actual_set:
            verdict = "MISS_ALL"
            false_negative += len(expected)
        elif not expected and actual_set:
            verdict = "FALSE_POS"
            false_positive += len(actual_set)
        elif expected & actual_set:
            missed = expected - actual_set
            extra = actual_set - expected
            verdict = f"PARTIAL (missing={missed}, extra={extra})"
            partial += 1
            false_negative += len(missed)
            false_positive += len(extra)
        else:
            verdict = "WRONG"
            false_negative += len(expected)
            false_positive += len(actual_set)

        print(f"  结果: {verdict}")

        results.append({
            "query": query,
            "expected": sorted(expected),
            "actual": sorted(actual_set),
            "verdict": verdict,
            "answer_preview": answer[:150],
            "elapsed_s": round(elapsed, 1),
        })

    # ── 汇总 ──
    accuracy = correct / total if total > 0 else 0
    easy_queries = [r for r, q in zip(results, queries) if q["difficulty"] == "easy"]
    hard_queries = [r for r, q in zip(results, queries) if q["difficulty"] == "hard"]
    easy_acc = (sum(1 for r in easy_queries if r["verdict"] == "OK") / len(easy_queries)
                 if easy_queries else 0)
    hard_acc = (sum(1 for r in hard_queries if r["verdict"] == "OK" or "PARTIAL" in str(r["verdict"]))
                 / len(hard_queries) if hard_queries else 0)

    print("\n" + "=" * 80)
    print("  评测汇总")
    print("=" * 80)
    print(f"  总 query 数:      {total}")
    print(f"  完全正确:         {correct}/{total} ({accuracy:.1%})")
    print(f"  部分正确(多工具): {partial}")
    print(f"  漏调工具次数:     {false_negative}")
    print(f"  误调工具次数:     {false_positive}")
    print(f"  简单 query 准确率: {easy_acc:.1%} ({len(easy_queries)} 条)")
    print(f"  复杂 query 覆盖率: {hard_acc:.1%} ({len(hard_queries)} 条)")

    # ── 按工具统计 ──
    print("\n  各工具调用统计:")
    tool_stats = {
        "query_workout_tool": {"tp": 0, "fp": 0, "fn": 0},
        "analyze_progress_tool": {"tp": 0, "fp": 0, "fn": 0},
        "rag_search_tool": {"tp": 0, "fp": 0, "fn": 0},
    }
    for r, q in zip(results, queries):
        exp = set(q["expected_tools"])
        act = set(r["actual"])
        for tool in tool_stats:
            if tool in exp and tool in act:
                tool_stats[tool]["tp"] += 1
            elif tool not in exp and tool in act:
                tool_stats[tool]["fp"] += 1
            elif tool in exp and tool not in act:
                tool_stats[tool]["fn"] += 1

    for tool, s in tool_stats.items():
        name = tool.replace("_tool", "")
        prec = s["tp"] / (s["tp"] + s["fp"]) if (s["tp"] + s["fp"]) > 0 else 0
        rec = s["tp"] / (s["tp"] + s["fn"]) if (s["tp"] + s["fn"]) > 0 else 0
        print(f"  {name}: 精确率={prec:.1%} 召回率={rec:.1%} (TP={s['tp']} FP={s['fp']} FN={s['fn']})")

    # ── 错误分析 ──
    errors = [r for r in results if r["verdict"] != "OK"]
    if errors:
        print("\n  错误详情:")
        for r in errors:
            print(f"  [{_safe(str(r['verdict']))}] {_safe(r['query'])}")
            print(f"    预期: {r['expected']} | 实际: {r['actual']}")

    # 保存详细结果
    output_file = Path(__file__).parent / "agent_routing_results.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump({
            "summary": {
                "total": total,
                "correct": correct,
                "accuracy": accuracy,
                "partial": partial,
                "false_negative": false_negative,
                "false_positive": false_positive,
                "easy_accuracy": easy_acc,
                "hard_coverage": hard_acc,
            },
            "details": results,
        }, f, ensure_ascii=False, indent=2)
    print(f"\n详细结果已保存到: {output_file}")

    print("=" * 80)
    print("  评测完成。")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
