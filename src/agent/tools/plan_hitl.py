"""训练计划的人工确认（HITL）共用逻辑。

``create_training_plan_tool`` 和 ``update_training_plan_tool`` 都需要在保存前
展示计划预览并等待用户确认，区别只在提示文案。把 ``interrupt`` 的载荷格式
集中在这里，前端只需要认一种 ``confirm_plan`` action。
"""

from __future__ import annotations

from typing import Any

from agent.utils.config import config
from agent.utils.utility import get_graph_thread_id


def preview_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """裁掉预览不需要的元字段（plan_id/created_at/source 由保存时回填）。"""
    return {key: value for key, value in plan.items() if key not in {"plan_id", "created_at", "source"}}


def request_plan_confirmation(
    plan: dict[str, Any],
    message: str = "即将生成训练计划，请确认动作安排；可以逐个更换动作。",
    mode: str = "create",
) -> dict[str, Any] | None:
    """在保存前请求用户确认计划预览。

    Args:
        plan: 计划正文。
        message: 卡片标题下的说明，创建和修改用不同文案。
        mode: create / update；前端据此把按钮文案改成「确认生成/确认修改」。

    Returns:
        None —— 确认开关关闭或不在 Agent 图中，调用方直接保存；
        dict —— 用户选择 ``{"approved": bool, "edits": list | None}``。
    """
    if not config.plan_confirm_enabled or get_graph_thread_id() is None:
        return None

    from langgraph.types import interrupt  # noqa: PLC0415

    decision = interrupt(
        {
            "action": "confirm_plan",
            "message": message,
            "mode": mode,
            "plan": preview_plan(plan),
        }
    )
    return decision if isinstance(decision, dict) else {"approved": bool(decision)}
