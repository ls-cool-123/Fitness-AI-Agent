"""口语/中英文输入归一化测试。"""

from __future__ import annotations

import pytest

from agent.plans.normalize import (
    expand_focus_token,
    normalize_experience,
    normalize_muscle,
    normalize_muscle_list,
    normalize_split,
    parse_day_focus,
)


@pytest.mark.unit
def test_experience_aliases() -> None:
    assert normalize_experience("无训练经验") == "beginner"
    assert normalize_experience("新手") == "beginner"
    assert normalize_experience("有训练经验") == "experienced"
    assert normalize_experience("老手") == "experienced"
    assert normalize_experience("不知道") is None


@pytest.mark.unit
def test_experience_option_letters_and_free_text() -> None:
    """AI 用 A/B 提问时，用户只回 A 也要能判断为新手。"""
    assert normalize_experience("A") == "beginner"
    assert normalize_experience("选A") == "beginner"
    assert normalize_experience("选项 A") == "beginner"
    assert normalize_experience("A. 新手") == "beginner"
    assert normalize_experience("B") == "experienced"
    assert normalize_experience("选B") == "experienced"
    assert normalize_experience("我是新手") == "beginner"
    assert normalize_experience("没有训练经验") == "beginner"
    assert normalize_experience("1") == "beginner"
    assert normalize_experience("2") == "experienced"


@pytest.mark.unit
def test_split_aliases() -> None:
    assert normalize_split("三分化") == "three_day"
    assert normalize_split("3") == "three_day"
    assert normalize_split("五分化") == "five_day"
    assert normalize_split("5") == "five_day"
    assert normalize_split("四分化") is None


@pytest.mark.unit
def test_split_option_letters() -> None:
    """分化题里的 A/B 也要能解析。"""
    assert normalize_split("A") == "three_day"
    assert normalize_split("选A") == "three_day"
    assert normalize_split("B") == "five_day"
    assert normalize_split("选B") == "five_day"
    assert normalize_split("1") == "three_day"
    assert normalize_split("2") == "five_day"


@pytest.mark.unit
def test_muscle_aliases_and_expansions() -> None:
    assert normalize_muscle("胸肌") == "胸"
    assert normalize_muscle("腿后侧") == "腘绳肌"
    assert expand_focus_token("推") == ["胸", "肩", "三头"]
    assert expand_focus_token("拉") == ["背", "二头"]
    assert "股四头" in expand_focus_token("腿")
    assert normalize_muscle_list(["胸、肩、三头"]) == ["胸", "肩", "三头"]
    assert normalize_muscle_list("推") == ["胸", "肩", "三头"]


@pytest.mark.unit
def test_parse_day_focus_three_days() -> None:
    days, error = parse_day_focus(["推", "拉", "腿"], "three_day")
    assert error is None
    assert days is not None
    assert len(days) == 3
    assert days[0] == ["胸", "肩", "三头"]


@pytest.mark.unit
def test_parse_day_focus_length_mismatch() -> None:
    days, error = parse_day_focus(["胸", "背"], "three_day")
    assert days is None
    assert error is not None
    assert "3" in error


@pytest.mark.unit
def test_parse_day_focus_none_uses_default() -> None:
    days, error = parse_day_focus(None, "five_day")
    assert days is None
    assert error is None
