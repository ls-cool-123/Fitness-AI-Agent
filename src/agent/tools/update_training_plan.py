"""修改训练计划工具 —— 在已有计划里按动作名替换，保留其他动作不变。

和 ``create_training_plan_tool`` 的分工：
- 用户还没有计划 → create（收集经验/分化/每日部位，生成整份计划）；
- 用户已有计划、只想换某个动作 → update（读最新计划，替换后确认保存）。

修改同样走 HITL：``interrupt(confirm_plan)`` → 前端计划确认卡片 → resume 后
``update_plan_data`` 覆盖原计划，不会新建一份重复计划。
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import tool
from loguru import logger

from agent.plans.generator import PlanValidationError, apply_named_swaps, apply_swaps
from agent.plans.service import get_latest_plan, get_plan, update_plan_data
from agent.tools.plan_hitl import request_plan_confirmation


def _needs_info(message: str, missing: list[str]) -> str:
    """返回缺信息结果，让 Agent 继续追问。"""
    return json.dumps(
        {"status": "needs_info", "missing": missing, "question": message, "message": message},
        ensure_ascii=False,
    )


def _normalize_swaps(raw: object) -> list[dict[str, Any]] | None:
    """把 LLM 可能传的 dict / JSON 字符串 / 列表统一成列表。"""
    if raw is None:
        return None
    if isinstance(raw, dict):
        return [raw]
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return _normalize_swaps(parsed)
    if isinstance(raw, (list, tuple)):
        return [item for item in raw if isinstance(item, dict)]
    return None


@tool
async def update_training_plan_tool(
    user_id: str,
    plan_id: str | None = None,
    swaps: list[dict] | None = None,
) -> str:
    """修改已有训练计划里的动作，保留其他训练日/动作不变。

    当用户**已经有一份计划**并要求替换某个动作时使用，例如：
    - "把哑铃卧推换成杠铃卧推"
    - "计划里的深蹲换成前蹲，其他不变"
    - "帮我把刚才计划里的飞鸟换掉"

    什么时候不要用：
    - 计划还在确认卡片中、尚未保存 → 提示用户在上方计划卡片/计划表里直接下拉替换，不要调用工具
    - 用户还没有计划、要从零制定 → 用 create_training_plan_tool
    - 用户想整体重新排一份计划（换分化/换每天部位） → 用 create_training_plan_tool
    - 只问动作要领/理论 → 用 rag_search_tool

    Args:
        user_id: 用户标识，会被系统注入的真实 user_id 覆盖。
        plan_id: 要修改的计划 id；省略则使用该用户最新创建的计划。
        swaps: 替换列表，格式
            ``[{"old_name": "哑铃卧推", "new_name": "杠铃卧推"}]``。
            也兼容 ``from`` / ``to`` 字段名。用户点名替换时允许跨水平
            （例如新手计划里换杠铃卧推），但会在计划里加提示。

    Returns:
        JSON 字符串：
        - ``{"status":"needs_info","question":"..."}`` 计划不存在/动作不明确；
        - ``{"status":"cancelled"}`` 用户取消；
        - ``{"status":"saved","plan_id":"...","plan":{...}}`` 已更新。
    """
    # Agent 调用时强制使用真实 user_id
    from agent.tools import current_user_id  # noqa: PLC0415

    enforced = current_user_id.get()
    if enforced:
        user_id = enforced

    normalized_swaps = _normalize_swaps(swaps)
    if not normalized_swaps:
        return _needs_info(
            "要把计划里的哪个动作换成什么？例如“把哑铃卧推换成杠铃卧推”。",
            ["swaps"],
        )

    if plan_id:
        plan = await get_plan(user_id, plan_id)
    else:
        plan = await get_latest_plan(user_id)
    if plan is None:
        return _needs_info(
            "还没有找到可修改的训练计划。先让我帮你制定一份，或者告诉我具体是哪一份计划。",
            ["plan_id"],
        )

    try:
        updated = apply_named_swaps(plan, normalized_swaps, allow_level_mismatch=True)
    except PlanValidationError as exc:
        return _needs_info(str(exc), ["swaps"])

    decision = request_plan_confirmation(
        updated,
        message="即将更新训练计划，请确认替换结果；还可以继续更换其他动作。",
        mode="update",
    )
    if decision is not None:
        if not decision.get("approved"):
            logger.info("用户取消了训练计划修改")
            return json.dumps(
                {"status": "cancelled", "message": "用户取消了本次计划修改，原计划保持不变。"},
                ensure_ascii=False,
            )
        edits = decision.get("edits")
        if edits:
            try:
                # 卡片回传的是所有 slot；允许用户保留刚换上的跨水平动作
                updated = apply_swaps(updated, edits, allow_level_mismatch=True)
            except PlanValidationError as exc:
                logger.warning(f"训练计划修改确认失败: {exc}")
                return json.dumps({"error": str(exc)}, ensure_ascii=False)

    target_plan_id = str(plan.get("plan_id") or plan_id or "")
    if not target_plan_id:
        return _needs_info("计划缺少 id，无法保存修改。请重新生成一份计划。", ["plan_id"])

    try:
        saved = await update_plan_data(user_id, target_plan_id, updated)
    except Exception as exc:  # noqa: BLE001 - 工具异常要转 JSON，不能中断 ReAct 循环
        logger.exception("保存训练计划修改失败")
        return json.dumps({"error": f"保存训练计划修改失败: {exc}"}, ensure_ascii=False)
    if saved is None:
        return _needs_info("这份计划已经不存在或不属于当前用户，无法修改。", ["plan_id"])

    logger.info(f"训练计划已更新: user={user_id}, plan_id={target_plan_id}")
    return json.dumps(
        {
            "status": "saved",
            "plan_id": target_plan_id,
            "plan": saved,
            "message": "训练计划已更新并保存，其他动作保持不变。",
        },
        ensure_ascii=False,
    )
