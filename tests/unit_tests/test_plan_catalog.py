"""动作库完整性测试。

这些断言防止「新增动作时漏了某个肌群/写了重复名字/计划模板引用了不存在的动作」
这类不会报错但会静默生成空计划的问题。
"""

from __future__ import annotations

import pytest

from agent.plans.catalog import (
    EXERCISES,
    MUSCLE_GROUPS,
    MUSCLE_GROUP_NAMES,
    exercises_for_group,
    find_exercise,
)
from agent.plans.generator import SPLIT_TEMPLATES


@pytest.mark.unit
def test_ten_muscle_groups_exist() -> None:
    assert [group.name for group in MUSCLE_GROUPS] == [
        "胸",
        "背",
        "肩",
        "二头",
        "三头",
        "股四头",
        "臀",
        "腘绳肌",
        "小腿",
        "核心",
    ]


@pytest.mark.unit
def test_every_group_has_beginner_and_experienced_exercises() -> None:
    """每个肌群至少 2 个纯新手动作、2 个纯老手动作，否则分化模板会缺动作。"""
    for group in MUSCLE_GROUPS:
        beginner = [exercise for exercise in EXERCISES if exercise.muscle_group == group.name and exercise.level == "beginner"]
        experienced = [exercise for exercise in EXERCISES if exercise.muscle_group == group.name and exercise.level == "experienced"]
        assert len(beginner) >= 2, f"{group.name} 新手动作不足: {len(beginner)}"
        assert len(experienced) >= 2, f"{group.name} 老手动作不足: {len(experienced)}"


@pytest.mark.unit
def test_exercise_names_are_unique() -> None:
    names = [exercise.name for exercise in EXERCISES]
    assert len(names) == len(set(names))


@pytest.mark.unit
def test_split_templates_reference_valid_groups_and_exercises() -> None:
    for split, days in SPLIT_TEMPLATES.items():
        assert len(days) == (3 if split == "three_day" else 5)
        for day in days:
            assert day["focus"]
            assert set(day["focus"]) <= MUSCLE_GROUP_NAMES
            for group in day["focus"]:
                assert exercises_for_group(group, "beginner"), f"{split}/{group} 没有新手动作"


@pytest.mark.unit
def test_level_filtering() -> None:
    """新手筛选不应返回纯老手动作；老手筛选可以返回新手动作。"""
    chest_beginner = exercises_for_group("胸", "beginner")
    chest_experienced = exercises_for_group("胸", "experienced")
    assert chest_beginner
    assert all(exercise.level in ("beginner", "all") for exercise in chest_beginner)
    assert any(exercise.level == "experienced" for exercise in chest_experienced)


@pytest.mark.unit
def test_find_exercise_resolves_equipment_prefix_and_alias() -> None:
    """用户说「杠铃卧推/杠铃深蹲」时要能解析到动作库标准名。"""
    assert find_exercise("杠铃卧推") is not None
    assert find_exercise("杠铃卧推").name == "卧推"
    assert find_exercise("杠铃深蹲").name == "深蹲"
    assert find_exercise("哑铃卧推").name == "哑铃卧推"
    assert find_exercise("不存在的动作") is None
