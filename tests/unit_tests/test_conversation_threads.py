"""对话线程与会话持久化的单元测试。

锁住三件事：
1. thread_id 由 user + conversation 两级组成，不再直接用 user_id；
2. 工具在 Agent 图外被调用时不会 interrupt（POST /workout/add 不受影响）；
3. 关闭 HITL 开关时不产生确认点。
"""

from __future__ import annotations

import pytest


@pytest.mark.unit
def test_thread_id_includes_conversation() -> None:
    """不同对话必须落在不同线程上，否则历史会串。"""
    from agent.api.chat import _resolve_thread_id

    assert _resolve_thread_id("u-1", "abc") == "u-1:abc"
    assert _resolve_thread_id("u-1", "xyz") == "u-1:xyz"
    assert _resolve_thread_id("u-1", "abc") != _resolve_thread_id("u-1", "xyz")


@pytest.mark.unit
def test_thread_id_falls_back_to_default_conversation() -> None:
    """未传 conversation_id 的旧前端仍然可用，落到 default 线程。"""
    from agent.api.chat import _resolve_thread_id

    assert _resolve_thread_id("u-1", None) == "u-1:default"
    assert _resolve_thread_id("u-1", "") == "u-1:default"


@pytest.mark.unit
def test_threads_of_different_users_never_collide() -> None:
    """即使用户名里含冒号，拼接结果也不能撞车到另一个用户。"""
    from agent.api.chat import _resolve_thread_id

    assert _resolve_thread_id("a:b", "c") != _resolve_thread_id("a", "b:c")


@pytest.mark.unit
def test_tool_outside_graph_has_no_thread_id() -> None:
    """图外调用（/workout/add）拿不到 thread_id，因此不会触发 interrupt。"""
    from agent.tools.add_workout import _graph_thread_id, _request_confirmation

    assert _graph_thread_id() is None
    assert _request_confirmation(object()) is None


@pytest.mark.unit
def test_confirmation_disabled_by_config(monkeypatch) -> None:
    """HITL 开关关闭时，即使在图内也不应暂停。"""
    from agent.tools import add_workout as module

    monkeypatch.setattr(module.config, "workout_confirm_enabled", False)
    monkeypatch.setattr(module, "_graph_thread_id", lambda: "u-1:default")

    assert module._request_confirmation(object()) is None
