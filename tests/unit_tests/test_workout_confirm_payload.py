"""训练记录确认载荷的换算测试。

工具入参的 ``reps`` 是**总次数**，确认卡片按"组数 × 每组次数"展示。
这两层语义不一致过：LLM 按 docstring 的旧说法传了每组次数，落库后总容量
只剩 1/5。这组测试把换算钉死。
"""

from __future__ import annotations

import pytest

from agent.parser.workout_parser import ParsedExercise


@pytest.mark.unit
def test_preview_exposes_reps_per_set() -> None:
    """5 组 × 5 次（总 25）应给出 reps_per_set=5。"""
    from agent.tools.add_workout import _preview_item

    exercise = ParsedExercise(name="深蹲", sets=5, reps=25, weight_kg=80)
    item = _preview_item(exercise)

    assert item["reps"] == 25
    assert item["reps_per_set"] == 5
    assert item["sets"] == 5
    assert item["weight_kg"] == 80


@pytest.mark.unit
def test_preview_without_sets_has_no_reps_per_set() -> None:
    """有氧类动作没有组数，不应该硬除出一个 per-set 值。"""
    from agent.tools.add_workout import _preview_item

    exercise = ParsedExercise(name="慢跑", sets=None, reps=None)
    item = _preview_item(exercise)

    assert item["reps_per_set"] is None


@pytest.mark.unit
def test_normalize_edits_converts_per_set_to_total() -> None:
    """前端回传的 reps_per_set 要换算成总次数再交给 build_workout。"""
    from agent.tools.add_workout import _normalize_edits

    normalized = _normalize_edits(
        [{"name": "深蹲", "sets": 5, "reps_per_set": 5, "weight_kg": 80}]
    )

    assert normalized[0]["reps"] == 25
    assert "reps_per_set" not in normalized[0]


@pytest.mark.unit
def test_normalize_edits_keeps_legacy_total_reps() -> None:
    """直接传总次数的调用方（旧前端）不受影响。"""
    from agent.tools.add_workout import _normalize_edits

    normalized = _normalize_edits([{"name": "深蹲", "sets": 5, "reps": 25}])

    assert normalized[0]["reps"] == 25
