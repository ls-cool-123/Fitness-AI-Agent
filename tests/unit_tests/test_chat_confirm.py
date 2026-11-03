"""POST /chat/confirm 的行为契约测试。

不启动 FastAPI（会触发 MySQL/Qdrant 初始化），直接调用路由函数，覆盖三条
分支：无待确认任务 → 409；同意 → resume 并返回答复；拒绝 → resume 且不落库
（是否落库由工具在 resume 后决定，这里只验证指令正确下发）。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage
from langgraph.types import Command


class _FakeTask:
    def __init__(self, interrupts: list[object]) -> None:
        self.interrupts = interrupts


class _FakeState:
    def __init__(self, tasks: list[_FakeTask]) -> None:
        self.tasks = tasks
        self.values: dict = {"messages": []}


class _FakeAgent:
    """记录收到的 resume 指令，并按需返回一条 AI 消息。"""

    def __init__(self, pending: bool) -> None:
        self._pending = pending
        self.received: list[Command] = []
        self.configs: list[dict] = []

    async def aget_state(self, config: dict) -> _FakeState:
        self.configs.append(config)
        if self._pending:
            return _FakeState([_FakeTask([SimpleNamespace(id="i-1", value={"action": "confirm_workout"})])])
        return _FakeState([])

    async def ainvoke(self, payload: object, config: dict) -> dict:
        assert isinstance(payload, Command)
        self.received.append(payload)
        return {"messages": [AIMessage(content="已为你记录本次训练")]}


@pytest.mark.unit
@pytest.mark.anyio
async def test_confirm_returns_409_when_nothing_pending(monkeypatch) -> None:
    """重复点击确认时不能再次写库，必须返回 409。"""
    from fastapi import HTTPException

    from agent.api import chat as chat_module

    agent = _FakeAgent(pending=False)
    monkeypatch.setattr(chat_module, "get_agent", lambda: agent)

    with pytest.raises(HTTPException) as excinfo:
        await chat_module.confirm(
            chat_module.ConfirmRequest(user_id="u-1", conversation_id="c-1", approved=True)
        )

    assert excinfo.value.status_code == 409
    assert agent.received == [], "没有待确认任务时不应下发 resume"


@pytest.mark.unit
@pytest.mark.anyio
async def test_confirm_resumes_with_approval_and_edits(monkeypatch) -> None:
    """用户在卡片里改过的数字要原样透传给工具。"""
    from agent.api import chat as chat_module

    agent = _FakeAgent(pending=True)
    monkeypatch.setattr(chat_module, "get_agent", lambda: agent)

    response = await chat_module.confirm(
        chat_module.ConfirmRequest(
            user_id="u-1",
            conversation_id="c-1",
            approved=True,
            edits=[{"name": "深蹲", "sets": 5, "reps": 5, "weight_kg": 100}],
        )
    )

    assert response.answer == "已为你记录本次训练"
    assert response.interrupt is None
    resume_payload = agent.received[0].resume
    assert resume_payload["approved"] is True
    assert resume_payload["edits"][0]["weight_kg"] == 100


@pytest.mark.unit
@pytest.mark.anyio
async def test_confirm_uses_conversation_scoped_thread(monkeypatch) -> None:
    """确认必须落在发起对话的同一条线程上，否则恢复的是别人的上下文。"""
    from agent.api import chat as chat_module

    agent = _FakeAgent(pending=True)
    monkeypatch.setattr(chat_module, "get_agent", lambda: agent)

    await chat_module.confirm(
        chat_module.ConfirmRequest(user_id="u-1", conversation_id="c-9", approved=False)
    )

    thread_id = agent.configs[0]["configurable"]["thread_id"]
    assert thread_id == chat_module._resolve_thread_id("u-1", "c-9")


@pytest.mark.unit
@pytest.mark.anyio
async def test_confirm_passes_plan_swaps_through(monkeypatch) -> None:
    """计划确认卡片回传的 slot_id/exercise_name 要原样进入 resume。"""
    from agent.api import chat as chat_module

    agent = _FakeAgent(pending=True)
    monkeypatch.setattr(chat_module, "get_agent", lambda: agent)

    await chat_module.confirm(
        chat_module.ConfirmRequest(
            user_id="u-1",
            conversation_id="c-1",
            approved=True,
            edits=[{"slot_id": "d1e1", "exercise_name": "哑铃卧推"}],
        )
    )

    resume_payload = agent.received[0].resume
    assert resume_payload["approved"] is True
    assert resume_payload["edits"] == [{"slot_id": "d1e1", "exercise_name": "哑铃卧推"}]
