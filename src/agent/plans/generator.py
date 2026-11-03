"""训练计划生成器（纯函数）。

生成规则是确定性的：同一组输入永远得到同一份计划。这不是为了「可复现」好看，
而是 HITL 的硬要求——``interrupt()`` 恢复时工具会从头重新执行，如果生成过程带
随机 id/随机动作，用户换动作时引用的 slot 就对不上。
"""

from __future__ import annotations

import copy
from typing import Any

from agent.plans.catalog import (
    EXERCISE_BY_NAME,
    EXERCISES,
    MUSCLE_GROUP_NAMES,
    ExerciseSpec,
    exercise_pattern,
    find_exercise,
    level_allows,
)
from agent.plans.normalize import (
    Experience,
    Split,
    normalize_avoid,
    normalize_experience,
    normalize_goal,
    normalize_muscle_list,
    normalize_plan_name,
    normalize_split,
    parse_day_focus,
)

SPLIT_LABELS: dict[Split, str] = {
    "three_day": "三分化",
    "five_day": "五分化",
}

EXPERIENCE_LABELS: dict[Experience, str] = {
    "beginner": "新手",
    "experienced": "有经验",
}

SPLIT_TEMPLATES: dict[Split, tuple[dict[str, Any], ...]] = {
    "three_day": (
        {"title": "推日", "focus": ("胸", "肩", "三头")},
        {"title": "拉日", "focus": ("背", "二头")},
        {"title": "腿日", "focus": ("股四头", "臀", "腘绳肌", "小腿", "核心")},
    ),
    "five_day": (
        {"title": "胸日", "focus": ("胸",)},
        {"title": "背日", "focus": ("背",)},
        {"title": "肩日", "focus": ("肩",)},
        {"title": "手臂日", "focus": ("二头", "三头")},
        {"title": "腿 + 核心日", "focus": ("股四头", "臀", "腘绳肌", "小腿", "核心")},
    ),
}

WARMUP = "5-10 分钟动态热身 + 第一个动作 2 组轻重量热身"
MAX_EXERCISES_PER_DAY = 6


class PlanValidationError(ValueError):
    """计划输入/换动作校验失败。调用方应把 message 交回用户继续追问。"""


def _default_days(split: Split) -> list[dict[str, Any]]:
    """返回分化模板的可变副本。"""
    return [
        {"title": item["title"], "focus": list(item["focus"])}
        for item in SPLIT_TEMPLATES[split]
    ]


def _target_count(experience: Experience, focus_count: int) -> int:
    """每天安排几个动作：新手少一点，覆盖肌群多时多一点。"""
    target = 4 if experience == "beginner" else 5
    if focus_count >= 4:
        target += 1
    return max(4, min(6, target))


def _prescription(exercise: ExerciseSpec, experience: Experience, goal: str) -> tuple[int, str, int]:
    """按经验 + 目标给出组数/次数/休息。"""
    # 平板支撑这类按秒计的动作保留自己的时长
    if "秒" in exercise.default_reps:
        return 3, exercise.default_reps, 45

    if goal == "力量":
        if exercise.is_compound:
            return 5, "3-6", 180
        return 3, "8-12", 90
    if goal == "减脂":
        return 3, "12-15", 60

    # 增肌 / 塑形
    if experience == "beginner":
        if exercise.is_compound:
            return 3, "8-12", 90
        return 3, "12-15", 60
    if exercise.is_compound:
        return 4, "6-10", 120
    return 3, "10-15", 75


def _exercise_payload(exercise: ExerciseSpec, experience: Experience, goal: str, note: str | None) -> dict[str, Any]:
    """把动作 + 处方组装成计划里的一个 slot。"""
    sets, reps, rest = _prescription(exercise, experience, goal)
    return {
        "name": exercise.name,
        "muscle_group": exercise.muscle_group,
        "sets": sets,
        "reps": reps,
        "rest_seconds": rest,
        "note": note,
        "alternatives": [],
    }


def _is_avoided(exercise: ExerciseSpec, avoid: list[str]) -> bool:
    """按动作名/别名做关键词排除。"""
    haystack = [exercise.name, *exercise.aliases]
    lowered = [item.lower() for item in haystack]
    return any(keyword.lower() in item for keyword in avoid for item in lowered)


def _pick_for_day(
    day: dict[str, Any],
    experience: Experience,
    goal: str,
    used: set[str],
    preferred: list[str],
    avoid: list[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    """为一天选动作，返回 (slots, warnings)。

    规则：用户点名的动作优先、按选择顺序放在最前；不足目标数量时再补
    推荐动作；无论如何一天最多 ``MAX_EXERCISES_PER_DAY`` 个。
    """
    warnings: list[str] = []
    focus: list[str] = day["focus"]
    target = _target_count(experience, len(focus))

    pool = [
        exercise
        for exercise in EXERCISES
        if exercise.muscle_group in focus
        and exercise.muscle_group in MUSCLE_GROUP_NAMES
        and level_allows(exercise.level, experience)
        and exercise.name not in used
        and not _is_avoided(exercise, avoid)
    ]

    def rank(exercise: ExerciseSpec) -> tuple[int, int, int]:
        """用户点名优先 → 复合动作优先 → 动作库顺序。"""
        return (
            0 if exercise.name in preferred else 1,
            0 if exercise.is_compound else 1,
            EXERCISES.index(exercise),
        )

    # 1) 用户点名的动作优先，保持选择顺序；超过 6 个只保留前 6 个
    user_selected: list[ExerciseSpec] = []
    skipped_preferred = 0
    for name in preferred:
        exercise = find_exercise(name)
        if exercise is None or exercise not in pool or exercise in user_selected:
            continue
        if len(user_selected) >= MAX_EXERCISES_PER_DAY:
            skipped_preferred += 1
            continue
        user_selected.append(exercise)
    if skipped_preferred:
        warnings.append(
            f"第 {day['day']} 天你选了超过 {MAX_EXERCISES_PER_DAY} 个动作，"
            f"已按选择顺序保留前 {MAX_EXERCISES_PER_DAY} 个。"
        )
    selected: list[ExerciseSpec] = list(user_selected)

    # 2) 每个还没覆盖的 focus 肌群补一个推荐动作（不超过 6 个）
    for group in focus:
        if len(selected) >= MAX_EXERCISES_PER_DAY:
            break
        if any(exercise.muscle_group == group for exercise in selected):
            continue
        candidates = sorted((exercise for exercise in pool if exercise.muscle_group == group), key=rank)
        if candidates:
            selected.append(candidates[0])

    # 3) 补到目标数量；优先补动作最少的肌群，保持均衡
    while len(selected) < target and len(selected) < MAX_EXERCISES_PER_DAY:
        remaining = [exercise for exercise in pool if exercise not in selected]
        if not remaining:
            break
        counts = {group: sum(1 for exercise in selected if exercise.muscle_group == group) for group in focus}
        group = min(focus, key=lambda item: (counts.get(item, 0), focus.index(item)))
        candidates = sorted((exercise for exercise in remaining if exercise.muscle_group == group), key=rank)
        if candidates:
            selected.append(candidates[0])
            continue
        # 该肌群没有候选了，从剩下的里按 rank 补（保持确定性）
        selected.append(sorted(remaining, key=rank)[0])

    # 4) 用户选的动作保持原顺序在前，推荐动作按复合优先排在其后
    user_names = {exercise.name for exercise in user_selected}
    recommended = [exercise for exercise in selected if exercise.name not in user_names]
    recommended.sort(key=lambda exercise: (0 if exercise.is_compound else 1, EXERCISES.index(exercise)))
    selected = user_selected + recommended

    first_compound_index = next(
        (index for index, exercise in enumerate(selected) if exercise.is_compound),
        None,
    )
    slots: list[dict[str, Any]] = []
    for index, exercise in enumerate(selected, start=1):
        if exercise.is_compound:
            note = "主项：优先完成，逐周加重量" if first_compound_index == index - 1 else "复合动作，保持动作质量"
        else:
            note = None
        slot = _exercise_payload(exercise, experience, goal, note)
        slot["slot_id"] = f"d{day['day']}e{index}"
        slots.append(slot)

    used.update(slot["name"] for slot in slots)

    covered = {slot["muscle_group"] for slot in slots}
    for group in focus:
        if group in covered:
            continue
        if len(slots) >= MAX_EXERCISES_PER_DAY:
            warnings.append(
                f"第 {day['day']} 天已达到 {MAX_EXERCISES_PER_DAY} 个动作上限，未补充 {group}；"
                "可减少已选动作后重新生成。"
            )
        else:
            warnings.append(f"{group} 没有可用动作，已跳过。")
    if not any(EXERCISE_BY_NAME[slot["name"]].is_compound for slot in slots):
        warnings.append(f"第 {day['day']} 天没有复合动作，建议至少加入一个复合动作。")
    if len(slots) < 3:
        warnings.append(f"第 {day['day']} 天只安排了 {len(slots)} 个动作，训练量可能偏低。")
    return slots, warnings


def _alternatives_for(slot: dict[str, Any], used: set[str], avoid: list[str]) -> list[str]:
    """给一个 slot 生成同肌群、同动作模式、未被占用的替代动作。

    不再按 beginner/experienced 过滤：用户明确在下拉框里选动作时允许跨水平，
    由 ``apply_swaps(allow_level_mismatch=True)`` 加提示。这样新手计划里的
    「推胸」也能换成杠铃卧推，而不是只给新手动作。
    """
    current = EXERCISE_BY_NAME.get(slot["name"])
    if current is None:
        return []
    pattern = exercise_pattern(current)
    candidates = [
        exercise
        for exercise in EXERCISES
        if exercise.muscle_group == slot["muscle_group"]
        and exercise.name != current.name
        and exercise.name not in used
        and exercise_pattern(exercise) == pattern
        and not _is_avoided(exercise, avoid)
    ]
    candidates.sort(key=lambda exercise: (0 if exercise.is_compound == current.is_compound else 1, EXERCISES.index(exercise)))
    return [exercise.name for exercise in candidates[:3]]


def build_plan(
    *,
    experience: object,
    split: object,
    day_focus: object = None,
    focus_muscles: object = None,
    preferred_exercises: object = None,
    avoid_exercises: object = None,
    goal: object = "增肌",
    plan_name: object = None,
) -> dict[str, Any]:
    """生成一份完整的训练计划。

    Args:
        experience: beginner/experienced 或中文别名。
        split: three_day/five_day 或中文别名。
        day_focus: 可选的每日部位；字符串或列表，每项代表一天。
        focus_muscles: 用户重点想练的肌群，必须出现在某一天里。
        preferred_exercises: 用户点名的动作，尽量放进计划。
        avoid_exercises: 要避开的动作名/关键词。
        goal: 增肌/力量/减脂/塑形。
        plan_name: 可选自定义计划名。

    Raises:
        PlanValidationError: 输入缺失、分化天数不对、重点肌群没被覆盖。

    Returns:
        可直接 JSON 序列化的计划 dict（不含 plan_id/created_at/source）。
    """
    normalized_experience = normalize_experience(experience)
    if normalized_experience is None:
        raise PlanValidationError("训练经验需要是「无训练经验」或「有训练经验」。")
    normalized_split = normalize_split(split)
    if normalized_split is None:
        raise PlanValidationError("分化方式需要是「三分化」或「五分化」。")

    parsed_days, error = parse_day_focus(day_focus, normalized_split)
    if error:
        raise PlanValidationError(error)
    if parsed_days is None:
        days = _default_days(normalized_split)
    else:
        days = [{"title": "", "focus": focus} for focus in parsed_days]

    focus = normalize_muscle_list(focus_muscles)
    covered = {group for day in days for group in day["focus"]}
    missing_focus = [group for group in focus if group not in covered]
    if missing_focus:
        raise PlanValidationError(
            f"重点部位（{'、'.join(missing_focus)}）不在任何训练日的安排里，请把它加到某一天，或取消这个重点。"
        )

    preferred_names: list[str] = []
    if isinstance(preferred_exercises, str):
        raw_list: list[str] = [preferred_exercises]
    elif isinstance(preferred_exercises, (list, tuple, set)):
        raw_list = [str(item) for item in preferred_exercises]
    else:
        raw_list = []
    for item in raw_list:
        for piece in str(item).replace("，", ",").replace("、", ",").split(","):
            name = piece.strip()
            exercise = find_exercise(name)
            if exercise and exercise.name not in preferred_names:
                preferred_names.append(exercise.name)

    avoid = normalize_avoid(avoid_exercises)

    warnings: list[str] = []
    if normalized_experience == "beginner" and normalized_split == "five_day":
        warnings.append("新手做五分化，单个肌群训练频率偏低；建议先练 8-12 周三分化再切换。")
    for required in ("胸", "背", "股四头"):
        if required not in covered:
            warnings.append(f"本周没有安排 {required} 训练，注意上下肢/前后侧平衡。")

    custom_days = parsed_days is not None
    used: set[str] = set()
    plan_days: list[dict[str, Any]] = []
    for index, raw_day in enumerate(days, start=1):
        default_title = str(raw_day.get("title", "") or "")
        title = default_title or " / ".join(raw_day["focus"])
        # 用户自定义 day_focus 时，标题用部位组合；默认模板保留「推日/拉日」等
        if custom_days:
            title = " / ".join(raw_day["focus"])
        day = {
            "day": index,
            "title": title,
            "focus": list(raw_day["focus"]),
        }
        slots, day_warnings = _pick_for_day(day, normalized_experience, normalize_goal(goal), used, preferred_names, avoid)
        warnings.extend(day_warnings)
        plan_days.append(
            {
                "day": index,
                "title": day["title"],
                "focus": day["focus"],
                "warmup": WARMUP,
                "exercises": slots,
            }
        )

    # 全部选完后再算 alternatives，保证不会推荐同计划里已用的动作
    for day in plan_days:
        for slot in day["exercises"]:
            slot["alternatives"] = _alternatives_for(slot, used, avoid)

    name = normalize_plan_name(plan_name)
    if name is None:
        name = f"{SPLIT_LABELS[normalized_split]} · {EXPERIENCE_LABELS[normalized_experience]}"
        if focus:
            suffix = "、".join(focus)
            name += f" · {suffix}重点"

    return {
        "version": 1,
        "name": name,
        "experience": normalized_experience,
        "split": normalized_split,
        "goal": normalize_goal(goal),
        "focus_muscles": focus,
        "avoid_exercises": avoid,
        "days": plan_days,
        "warnings": warnings,
    }


def apply_swaps(plan: dict[str, Any], swaps: object, *, allow_level_mismatch: bool = False) -> dict[str, Any]:
    """应用用户换动作，返回新的计划 dict。

    Args:
        plan: ``build_plan`` 或数据库里的计划快照。
        swaps: ``[{"slot_id": "d1e1", "exercise_name": "哑铃卧推"}, ...]``；
            删除动作用 ``{"slot_id": "d1e1", "remove": true}``。
        allow_level_mismatch: 用户明确点名换某个动作时，允许跨水平（例如新手计划
            里换成杠铃卧推）。默认仍按水平校验，供常规 UI/PATCH 使用。

    Raises:
        PlanValidationError: slot 不存在、动作不存在、跨肌群、水平不匹配、最终重名。

    Returns:
        深拷贝后的新计划，``alternatives`` 已按最终动作集重算。
    """
    if swaps is None:
        return copy.deepcopy(plan)
    if not isinstance(swaps, (list, tuple)):
        raise PlanValidationError("换动作数据格式不对，需要 slot_id + exercise_name 的列表。")
    if len(swaps) > 30:
        raise PlanValidationError("一次最多换 30 个动作。")

    updated: dict[str, Any] = copy.deepcopy(plan)
    experience = normalize_experience(updated.get("experience"))
    if experience is None:
        raise PlanValidationError("计划里的训练经验字段无效。")
    goal = normalize_goal(updated.get("goal"))

    slots: dict[str, dict[str, Any]] = {}
    for day in updated.get("days", []):
        for slot in day.get("exercises", []):
            slot_id = str(slot.get("slot_id", ""))
            if slot_id:
                slots[slot_id] = slot

    removed_ids: set[str] = set()

    for raw_swap in swaps:
        if not isinstance(raw_swap, dict):
            raise PlanValidationError("换动作数据格式不对。")
        slot_id = str(raw_swap.get("slot_id", "")).strip()
        slot = slots.get(slot_id)
        if slot is None:
            raise PlanValidationError(f"没有找到动作位置 {slot_id or '(空)'}。")
        if raw_swap.get("remove") is True:
            removed_ids.add(slot_id)
            continue
        exercise_name = str(raw_swap.get("exercise_name", "")).strip()
        replacement = find_exercise(exercise_name)
        if replacement is None:
            raise PlanValidationError(f"动作库里没有「{exercise_name}」。")
        if replacement.muscle_group != slot.get("muscle_group"):
            raise PlanValidationError(f"「{exercise_name}」属于{replacement.muscle_group}，不能替换{slot.get('muscle_group')}动作。")
        if not allow_level_mismatch and not level_allows(replacement.level, experience):
            raise PlanValidationError(f"「{exercise_name}」不适合当前训练水平。")
        if allow_level_mismatch and not level_allows(replacement.level, experience):
            warning = f"「{exercise_name}」通常建议有经验者，已按你的要求替换。"
            warnings = updated.setdefault("warnings", [])
            if warning not in warnings:
                warnings.append(warning)
        sets, reps, rest = _prescription(replacement, experience, goal)
        slot.update(
            {
                "name": replacement.name,
                "muscle_group": replacement.muscle_group,
                "sets": sets,
                "reps": reps,
                "rest_seconds": rest,
                "note": "复合动作，保持动作质量" if replacement.is_compound else None,
            }
        )

    if removed_ids:
        for day in updated.get("days", []):
            day["exercises"] = [slot for slot in day.get("exercises", []) if slot.get("slot_id") not in removed_ids]
            if not day["exercises"]:
                raise PlanValidationError(f"第 {day.get('day', '?')} 天不能删除所有动作，请至少保留一个。")

    names = [slot["name"] for day in updated.get("days", []) for slot in day.get("exercises", [])]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise PlanValidationError("换动作后计划里出现重复动作：" + "、".join(duplicates) + "。请换一个。")

    used = set(names)
    avoid = normalize_avoid(updated.get("avoid_exercises", []))
    for day in updated.get("days", []):
        for slot in day.get("exercises", []):
            slot["alternatives"] = _alternatives_for(slot, used, avoid)
    return updated


def apply_named_swaps(plan: dict[str, Any], swaps: object, *, allow_level_mismatch: bool = True) -> dict[str, Any]:
    """按动作名换动作（AI 对话里用户通常说"把 A 换成 B"）。

    Args:
        plan: 已保存的计划快照。
        swaps: ``[{"old_name": "哑铃卧推", "new_name": "杠铃卧推"}]``。
        allow_level_mismatch: 用户点名替换时默认允许跨水平，避免"新手计划里
            换杠铃卧推"被静默拒绝。

    Raises:
        PlanValidationError: 旧动作不存在/在计划里出现多次，或新动作不合法。
    """
    if swaps is None:
        return copy.deepcopy(plan)
    if not isinstance(swaps, (list, tuple)):
        raise PlanValidationError("换动作数据格式不对，需要 old_name + new_name 的列表。")
    if not swaps:
        raise PlanValidationError("请告诉我要把哪个动作换成什么。")

    slots_by_name: dict[str, list[str]] = {}
    for day in plan.get("days", []):
        for slot in day.get("exercises", []):
            name = str(slot.get("name", ""))
            slot_id = str(slot.get("slot_id", ""))
            if name and slot_id:
                slots_by_name.setdefault(name, []).append(slot_id)

    normalized: list[dict[str, str]] = []
    for raw_swap in swaps:
        if not isinstance(raw_swap, dict):
            raise PlanValidationError("换动作数据格式不对。")
        old_name = str(raw_swap.get("old_name") or raw_swap.get("from") or "").strip()
        new_name = str(raw_swap.get("new_name") or raw_swap.get("to") or raw_swap.get("exercise_name") or "").strip()
        if not old_name or not new_name:
            raise PlanValidationError("需要同时给出 old_name（原动作）和 new_name（新动作）。")
        old_exercise = find_exercise(old_name)
        lookup_name = old_exercise.name if old_exercise else old_name
        slot_ids = slots_by_name.get(lookup_name, [])
        if not slot_ids:
            available = "、".join(list(slots_by_name)[:20])
            raise PlanValidationError(f"计划里没有「{old_name}」。当前动作有：{available}。")
        if len(slot_ids) > 1:
            raise PlanValidationError(f"「{old_name}」在计划里出现了多次，请指明是哪一天的动作。")
        normalized.append({"slot_id": slot_ids[0], "exercise_name": new_name})

    return apply_swaps(plan, normalized, allow_level_mismatch=allow_level_mismatch)


def refresh_alternatives(plan: dict[str, Any]) -> dict[str, Any]:
    """按当前动作库重算一份已保存计划的 alternatives。

    动作库可能后来调整了模式/新增动作，旧计划里存的 alternatives 会过时。
    读取计划时用它刷新，保证「推胸只推荐推胸」等规则对历史计划也生效。
    """
    updated = copy.deepcopy(plan)
    used = {
        str(slot.get("name", ""))
        for day in updated.get("days", [])
        for slot in day.get("exercises", [])
    }
    avoid = normalize_avoid(updated.get("avoid_exercises", []))
    for day in updated.get("days", []):
        for slot in day.get("exercises", []):
            slot["alternatives"] = _alternatives_for(slot, used, avoid)
    return updated


def plan_summary(plan: dict[str, Any], plan_id: str | None = None, source: str | None = None, created_at: str | None = None) -> dict[str, Any]:
    """构造列表页用的计划摘要。"""
    result = {
        "plan_id": plan_id or plan.get("plan_id"),
        "name": plan.get("name", ""),
        "experience": plan.get("experience", ""),
        "split": plan.get("split", ""),
        "source": source or plan.get("source", ""),
        "created_at": created_at or plan.get("created_at", ""),
        "day_count": len(plan.get("days", [])),
        "focus_muscles": plan.get("focus_muscles", []),
    }
    return result
