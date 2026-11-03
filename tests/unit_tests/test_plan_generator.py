"""计划生成器/换动作的纯函数测试（不依赖 MySQL/Qdrant）。"""

from __future__ import annotations

import pytest

from agent.plans.generator import PlanValidationError, apply_named_swaps, apply_swaps, build_plan


@pytest.mark.unit
def test_beginner_three_day_plan_shape() -> None:
    plan = build_plan(experience="无训练经验", split="三分化", focus_muscles=["胸"])

    assert len(plan["days"]) == 3
    assert all(4 <= len(day["exercises"]) <= 6 for day in plan["days"])
    assert plan["experience"] == "beginner"
    assert plan["split"] == "three_day"
    assert "胸" in plan["focus_muscles"]
    # 新手计划不应出现纯老手动作
    for day in plan["days"]:
        for slot in day["exercises"]:
            from agent.plans.catalog import EXERCISE_BY_NAME

            assert EXERCISE_BY_NAME[slot["name"]].level != "experienced"


@pytest.mark.unit
def test_experienced_five_day_plan_has_compounds_and_prescription() -> None:
    plan = build_plan(experience="有训练经验", split="五分化", goal="力量")

    assert len(plan["days"]) == 5
    assert all(5 <= len(day["exercises"]) <= 6 for day in plan["days"])
    for day in plan["days"]:
        assert any(slot["note"] and "主项" in slot["note"] or slot["sets"] == 5 for slot in day["exercises"])
        assert all(slot["sets"] >= 3 for slot in day["exercises"])
        assert all(slot["rest_seconds"] >= 60 for slot in day["exercises"])


@pytest.mark.unit
def test_preferred_exercise_is_included() -> None:
    plan = build_plan(experience="experienced", split="three_day", preferred_exercises=["卧推"])
    names = [slot["name"] for day in plan["days"] for slot in day["exercises"]]
    assert "卧推" in names


@pytest.mark.unit
def test_avoid_exercises_are_excluded() -> None:
    plan = build_plan(experience="experienced", split="three_day", avoid_exercises=["硬拉"])
    names = [slot["name"] for day in plan["days"] for slot in day["exercises"]]
    assert all("硬拉" not in name for name in names)


@pytest.mark.unit
def test_custom_day_focus_and_titles() -> None:
    plan = build_plan(
        experience="beginner",
        split="three_day",
        day_focus=["推", "拉", "腿"],
    )
    assert len(plan["days"]) == 3
    assert plan["days"][0]["focus"] == ["胸", "肩", "三头"]
    assert "胸" in plan["days"][0]["title"]


@pytest.mark.unit
def test_focus_muscle_not_in_day_focus_raises() -> None:
    with pytest.raises(PlanValidationError):
        build_plan(
            experience="beginner",
            split="three_day",
            day_focus=["胸", "背", "腿"],
            focus_muscles=["肩"],
        )


@pytest.mark.unit
def test_invalid_day_focus_length_raises() -> None:
    with pytest.raises(PlanValidationError):
        build_plan(experience="beginner", split="three_day", day_focus=["胸", "背"])


@pytest.mark.unit
def test_beginner_five_day_has_warning() -> None:
    plan = build_plan(experience="beginner", split="five_day")
    assert any("新手" in warning and "五分化" in warning for warning in plan["warnings"])


@pytest.mark.unit
def test_preferred_actions_are_first_then_recommendations() -> None:
    """用户选的动作按选择顺序排在前面，剩余位置才补推荐动作。"""
    chosen = ["器械推胸", "飞鸟", "俯卧撑", "哑铃卧推"]
    plan = build_plan(
        experience="新手",
        split="三分化",
        focus_muscles=["胸"],
        preferred_exercises=chosen,
    )
    names = [slot["name"] for slot in plan["days"][0]["exercises"]]

    assert names[:4] == chosen
    assert len(names) <= 6
    # 胸之外还有肩/三头，补推荐动作时应该覆盖到
    assert len(names) == 6


@pytest.mark.unit
def test_preferred_actions_are_capped_at_six() -> None:
    """用户选超过 6 个动作时，只保留前 6 个并给出提示。"""
    chosen = ["卧推", "上斜卧推", "上斜哑铃卧推", "下斜卧推", "飞鸟", "绳索夹胸", "俯卧撑"]
    plan = build_plan(
        experience="experienced",
        split="五分化",
        preferred_exercises=chosen,
    )
    day = plan["days"][0]
    names = [slot["name"] for slot in day["exercises"]]

    assert names == chosen[:6]
    assert any("超过 6 个动作" in warning for warning in plan["warnings"])


@pytest.mark.unit
def test_apply_named_swaps_replaces_only_requested_action() -> None:
    """按动作名替换：只换目标动作，其他动作原样保留；跨水平给提示。"""
    plan = build_plan(
        experience="新手",
        split="三分化",
        focus_muscles=["胸"],
        preferred_exercises=["哑铃卧推"],
    )
    before = [slot["name"] for slot in plan["days"][0]["exercises"]]
    assert "哑铃卧推" in before

    updated = apply_named_swaps(plan, [{"old_name": "哑铃卧推", "new_name": "杠铃卧推"}])
    after = [slot["name"] for slot in updated["days"][0]["exercises"]]

    # 动作库标准名是「卧推」，「杠铃卧推」通过别名解析到它
    assert "卧推" in after
    assert "哑铃卧推" not in after
    assert [name for name in before if name != "哑铃卧推"] == [name for name in after if name != "卧推"]
    assert any("通常建议有经验者" in warning for warning in updated["warnings"])


@pytest.mark.unit
def test_apply_named_swaps_missing_old_action_raises() -> None:
    plan = build_plan(experience="新手", split="三分化")
    with pytest.raises(PlanValidationError):
        apply_named_swaps(plan, [{"old_name": "不存在的动作", "new_name": "杠铃卧推"}])


@pytest.mark.unit
def test_apply_swaps_still_rejects_level_mismatch_by_default() -> None:
    plan = build_plan(experience="新手", split="三分化", focus_muscles=["胸"])
    slot = next(
        slot
        for day in plan["days"]
        for slot in day["exercises"]
        if slot["muscle_group"] == "胸"
    )
    with pytest.raises(PlanValidationError):
        apply_swaps(plan, [{"slot_id": slot["slot_id"], "exercise_name": "杠铃卧推"}])


@pytest.mark.unit
def test_alternatives_are_same_pattern_and_ignore_level() -> None:
    """下拉框只给同模式动作，且不再按新手/老手过滤。"""
    plan = build_plan(
        experience="新手",
        split="三分化",
        focus_muscles=["胸"],
        preferred_exercises=["器械推胸", "飞鸟"],
    )
    day = plan["days"][0]
    press = next(slot for slot in day["exercises"] if slot["name"] == "器械推胸")
    fly = next(slot for slot in day["exercises"] if slot["name"] == "飞鸟")

    # 推胸的候选里不能出现夹胸
    assert "飞鸟" not in press["alternatives"]
    assert "绳索夹胸" not in press["alternatives"]
    # 夹胸的候选里不能出现推胸
    assert "器械推胸" not in fly["alternatives"]
    assert "卧推" not in fly["alternatives"]
    # 新手计划也允许选老手动作（用户明确点选）
    assert "卧推" in press["alternatives"]
    assert "绳索夹胸" in fly["alternatives"]


@pytest.mark.unit
def test_apply_swaps_can_remove_an_action() -> None:
    plan = build_plan(experience="新手", split="三分化", focus_muscles=["胸"])
    slot = plan["days"][0]["exercises"][0]
    before = len(plan["days"][0]["exercises"])

    updated = apply_swaps(plan, [{"slot_id": slot["slot_id"], "remove": True}])

    assert len(updated["days"][0]["exercises"]) == before - 1
    assert slot["name"] not in [item["name"] for item in updated["days"][0]["exercises"]]


@pytest.mark.unit
def test_apply_swaps_cannot_remove_all_actions_in_a_day() -> None:
    plan = build_plan(experience="新手", split="三分化", focus_muscles=["胸"])
    slots = plan["days"][0]["exercises"]
    with pytest.raises(PlanValidationError):
        apply_swaps(plan, [{"slot_id": slot["slot_id"], "remove": True} for slot in slots])


@pytest.mark.unit
def test_apply_swaps_replaces_and_recomputes_alternatives() -> None:
    plan = build_plan(experience="experienced", split="five_day")
    first = plan["days"][0]["exercises"][0]
    replacement = next(
        name for name in first["alternatives"] if name != first["name"]
    )
    updated = apply_swaps(plan, [{"slot_id": first["slot_id"], "exercise_name": replacement}])

    assert updated["days"][0]["exercises"][0]["name"] == replacement
    assert updated["days"][0]["exercises"][0]["alternatives"]


@pytest.mark.unit
def test_apply_swaps_allows_permutation() -> None:
    """两个 slot 互换动作时，不要因为中间态重名而误报。"""
    plan = build_plan(experience="experienced", split="five_day")
    slots = plan["days"][0]["exercises"]
    assert len(slots) >= 2
    swaps = [
        {"slot_id": slots[0]["slot_id"], "exercise_name": slots[1]["name"]},
        {"slot_id": slots[1]["slot_id"], "exercise_name": slots[0]["name"]},
    ]
    updated = apply_swaps(plan, swaps)
    assert updated["days"][0]["exercises"][0]["name"] == slots[1]["name"]
    assert updated["days"][0]["exercises"][1]["name"] == slots[0]["name"]


@pytest.mark.unit
def test_apply_swaps_rejects_cross_group() -> None:
    plan = build_plan(experience="experienced", split="five_day")
    first = plan["days"][0]["exercises"][0]
    with pytest.raises(PlanValidationError):
        apply_swaps(plan, [{"slot_id": first["slot_id"], "exercise_name": "深蹲"}])


@pytest.mark.unit
def test_apply_swaps_rejects_duplicate_final_state() -> None:
    plan = build_plan(experience="experienced", split="five_day")
    first, second = plan["days"][0]["exercises"][:2]
    with pytest.raises(PlanValidationError):
        apply_swaps(
            plan,
            [
                {"slot_id": first["slot_id"], "exercise_name": second["name"]},
                {"slot_id": second["slot_id"], "exercise_name": second["name"]},
            ],
        )
