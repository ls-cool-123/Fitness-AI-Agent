"""制定训练计划工具 —— 对话式采集信息 → 预览确认 → 落库。

流程与 ``add_workout_tool`` 保持同一套 HITL 约束：

    LLM 收集经验/分化/每日部位 → create_training_plan_tool
      → 信息齐全：interrupt(confirm_plan) 暂停，前端展示计划预览
      → 用户换动作/确认 → Command(resume=...)
      → 应用换动作 → 写 training_plans

**不要在 interrupt 之前写库**：resume 时工具会从头重新执行。计划生成本身是
纯函数且 slot_id 确定性，所以重新执行得到同一份计划，用户换动作的 slot 不会漂移。
"""

from __future__ import annotations

import json

from langchain_core.tools import tool
from loguru import logger

from agent.plans.generator import PlanValidationError, apply_swaps, build_plan
from agent.plans.normalize import (
    Experience,
    Split,
    normalize_experience,
    normalize_muscle_list,
    normalize_split,
    parse_day_focus,
)
from agent.plans.service import save_plan
from agent.tools.plan_hitl import request_plan_confirmation


def _needs_info(message: str, missing: list[str]) -> str:
    """返回缺信息结果，让 Agent 按 message 继续追问。"""
    return json.dumps(
        {"status": "needs_info", "missing": missing, "question": message, "message": message},
        ensure_ascii=False,
    )


def _missing_questions(
    experience: Experience | None,
    split: Split | None,
    day_focus: object,
    auto_day_focus: bool,
) -> tuple[str, list[str]] | None:
    """按「一次只问一个」的顺序返回第一个缺失项。"""
    if experience is None:
        return "你之前有系统的力量训练经验吗？（A. 无训练经验 / B. 有训练经验）", ["experience"]
    if split is None:
        return "你想练三分化还是五分化？（A. 三分化 / B. 五分化）", ["split"]
    days, error = parse_day_focus(day_focus, split)
    if error:
        return error, ["day_focus"]
    if days is None and not auto_day_focus:
        expected = 3 if split == "three_day" else 5
        return (
            f"{expected} 分化需要 {expected} 个训练日。你想每天练哪些部位？"
            "可以说'推/拉/腿'，或者直接说'你安排'用默认模板。",
            ["day_focus"],
        )
    return None


@tool
async def create_training_plan_tool(
    user_id: str,
    experience: str = "",
    split: str = "",
    day_focus: list[str] | None = None,
    auto_day_focus: bool = False,
    focus_muscles: list[str] | None = None,
    preferred_exercises: list[str] | None = None,
    avoid_exercises: list[str] | None = None,
    goal: str = "增肌",
    plan_name: str | None = None,
) -> str:
    """为用户制定一份可执行的力量训练计划。

    当用户明确要求「制定/生成/安排训练计划」时使用，例如：
    - "帮我制定一个三分化训练计划"
    - "我想增肌，给我排个五分化计划"
    - "我是新手，应该怎么安排训练"

    什么时候不要用：
    - 用户已经有计划，只想换/替换某个动作 → 用 update_training_plan_tool，
      不要重新生成整份计划
    - 只问某个动作怎么做、训练理论、营养/恢复 → 用 rag_search_tool
    - 记录一次已经发生的训练 → 用 add_workout_tool
    - 查询/分析自己的训练历史 → 用 query_workout_tool 或 analyze_progress_tool
    - 只是问"训练计划一般怎么安排"这种理论问题 → 用 rag_search_tool，不要生成个人计划

    调用前请先按顺序问清楚（一次只问一个）：
    1. 训练经验：beginner（无/新手）或 experienced（有/老手）
    2. 分化：three_day（三分化）或 five_day（五分化）
    3. 每个训练日练哪些部位：三分化给 3 项、五分化给 5 项，每项一个字符串，
       例如 ["胸、肩、三头", "背、二头", "腿、臀、核心"]。用户说"推/拉/腿"
       也可以直接传。只有用户明确说"你安排/随便"时，才传 auto_day_focus=True
       使用默认模板；否则省略 day_focus 会让工具返回 needs_info 继续追问。

    Args:
        user_id: 用户标识（UUID 或用户名），会被系统注入的真实 user_id 覆盖。
        experience: beginner/experienced，也接受"新手/老手/无经验/有经验"，
            以及选项字母 A（新手）/ B（老手）。
        split: three_day/five_day，也接受"三分化/五分化/3/5"，
            以及选项字母 A（三分化）/ B（五分化）。
        day_focus: 每个训练日练哪些部位，长度必须等于分化天数。
        auto_day_focus: 用户说"你安排"时传 True，允许使用默认分化模板。
        focus_muscles: 用户特别想练的肌群，如 ["胸"]；必须出现在某个训练日里。
        preferred_exercises: 用户点名想放进计划的动作名，会尽量优先安排。
        avoid_exercises: 因伤病/偏好要避开的动作名或关键词，如 ["硬拉","深蹲"]。
        goal: 增肌/力量/减脂/塑形，默认增肌。
        plan_name: 可选自定义计划名，最多 100 字。

    Returns:
        JSON 字符串：
        - ``{"status":"needs_info","missing":[...],"question":"..."}`` 信息不全；
        - ``{"status":"cancelled"}`` 用户取消；
        - ``{"status":"saved","plan_id":"...","plan":{...}}`` 已保存。
    """
    # Agent 调用时强制使用真实 user_id，防止 LLM 幻觉
    from agent.tools import current_user_id  # noqa: PLC0415

    enforced = current_user_id.get()
    if enforced:
        user_id = enforced

    normalized_experience = normalize_experience(experience)
    normalized_split = normalize_split(split)

    missing = _missing_questions(normalized_experience, normalized_split, day_focus, auto_day_focus)
    if missing is not None:
        question, fields = missing
        return _needs_info(question, fields)

    # 到这里 experience/split 一定非空；类型收窄给 mypy/ruff 看
    assert normalized_experience is not None
    assert normalized_split is not None

    # 先做一次可读的校验：重点肌群必须在训练日安排里，否则让 Agent 追问
    days, day_error = parse_day_focus(day_focus, normalized_split)
    if day_error:
        return _needs_info(day_error, ["day_focus"])
    focus = normalize_muscle_list(focus_muscles)
    if days is not None and focus:
        covered = {group for item in days for group in item}
        missing_focus = [group for group in focus if group not in covered]
        if missing_focus:
            return _needs_info(
                f"重点部位（{'、'.join(missing_focus)}）不在任何训练日里。请把它加到某一天，或取消这个重点。",
                ["focus_muscles"],
            )

    try:
        plan = build_plan(
            experience=normalized_experience,
            split=normalized_split,
            day_focus=day_focus,
            focus_muscles=focus_muscles,
            preferred_exercises=preferred_exercises,
            avoid_exercises=avoid_exercises,
            goal=goal,
            plan_name=plan_name,
        )
    except PlanValidationError as exc:
        return _needs_info(str(exc), ["plan"])

    decision = request_plan_confirmation(plan)
    if decision is not None:
        if not decision.get("approved"):
            logger.info("用户取消了本次训练计划生成")
            return json.dumps(
                {"status": "cancelled", "message": "用户取消了本次计划生成，未保存任何数据。"},
                ensure_ascii=False,
            )
        edits = decision.get("edits")
        if edits:
            try:
                plan = apply_swaps(plan, edits, allow_level_mismatch=True)
            except PlanValidationError as exc:
                logger.warning(f"训练计划换动作失败: {exc}")
                return json.dumps({"error": str(exc)}, ensure_ascii=False)

    try:
        saved = await save_plan(user_id, plan, source="chat")
    except Exception as exc:  # noqa: BLE001 - 工具异常要转成 JSON，不能中断 ReAct 循环
        logger.exception("保存训练计划失败")
        return json.dumps({"error": f"保存训练计划失败: {exc}"}, ensure_ascii=False)

    logger.info(f"训练计划已保存: user={user_id}, plan_id={saved.get('plan_id')}")
    return json.dumps(
        {
            "status": "saved",
            "plan_id": saved.get("plan_id"),
            "plan": saved,
            "message": "训练计划已生成并保存，可在「人体图 → 我的计划」查看。",
        },
        ensure_ascii=False,
    )
