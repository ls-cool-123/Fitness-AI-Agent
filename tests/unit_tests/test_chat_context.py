"""聊天上下文管理测试 —— 锁住「对话历史不重复累积」这一不变量。

前端每轮都会重发全量历史。若后端原样转发给 Agent，这些消息因为不带 id
会被 add_messages 分配新 UUID，与 checkpointer 中已有消息匹配不上，从而被
当作新消息追加，导致 state 里的消息数按 O(N²) 膨胀。
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage


@pytest.mark.unit
@pytest.mark.anyio
async def test_first_turn_injects_system_message_and_full_history() -> None:
    """线程为空时（首轮）：注入 user_id 的 SystemMessage + 前端全量历史。"""
    from agent.api import chat as chat_module

    request = chat_module.ChatRequest(
        messages=[chat_module.ChatMessage(role="user", content="我想增肌")],
        user_id="u-1",
    )

    result = await chat_module._build_agent_input(request)

    assert isinstance(result[0], SystemMessage)
    assert "u-1" in result[0].content
    assert [m.content for m in result[1:]] == ["我想增肌"]


@pytest.mark.unit
@pytest.mark.anyio
async def test_existing_thread_sends_only_latest_user_message(monkeypatch) -> None:
    """线程已有历史时：只发最新一条用户消息，不重发历史，不重注 SystemMessage。"""
    from agent.api import chat as chat_module

    # 伪造一个已有历史的线程状态
    class _State:
        values = {"messages": [HumanMessage(content="我想增肌"), AIMessage(content="好的")]}

    async def fake_aget_state(_config):
        return _State()

    monkeypatch.setattr(chat_module.fitness_agent, "aget_state", fake_aget_state)

    request = chat_module.ChatRequest(
        messages=[
            chat_module.ChatMessage(role="user", content="我想增肌"),
            chat_module.ChatMessage(role="assistant", content="好的"),
            chat_module.ChatMessage(role="user", content="一周四天"),
        ],
        user_id="u-1",
    )

    result = await chat_module._build_agent_input(request)

    assert len(result) == 1
    assert isinstance(result[0], HumanMessage)
    assert result[0].content == "一周四天"


@pytest.mark.unit
@pytest.mark.anyio
async def test_history_grows_linearly_not_quadratically(monkeypatch) -> None:
    """多轮对话后，state 中的消息数应线性增长而非平方增长。

    这是本次修复的核心断言：模拟 10 轮对话，每轮前端重发全量历史，
    检查累计进入 Agent 的消息总数是 O(N) 而不是 O(N²)。
    """
    from agent.api import chat as chat_module

    turns = 10
    # 模拟 checkpointer：每轮把 Agent 的输入累积进去
    thread_state: list = []

    class _State:
        @property
        def values(self):
            return {"messages": thread_state}

    async def fake_aget_state(_config):
        return _State()

    monkeypatch.setattr(chat_module.fitness_agent, "aget_state", fake_aget_state)

    frontend_history: list[chat_module.ChatMessage] = []
    for i in range(turns):
        frontend_history.append(chat_module.ChatMessage(role="user", content=f"问题{i}"))
        request = chat_module.ChatRequest(messages=list(frontend_history), user_id="u-1")

        agent_input = await chat_module._build_agent_input(request)
        thread_state.extend(agent_input)
        # Agent 每轮追加一条 AI 回复
        thread_state.append(AIMessage(content=f"回答{i}"))
        frontend_history.append(
            chat_module.ChatMessage(role="assistant", content=f"回答{i}")
        )

    # 线性增长：1 条 SystemMessage + 每轮 (1 用户 + 1 AI) = 1 + 2*10 = 21
    assert len(thread_state) == 1 + 2 * turns
    # 平方增长会是 100+ 条，这里断言远低于该量级
    assert len(thread_state) < turns * turns

    # 每个问题只出现一次，没有重复副本
    contents = [m.content for m in thread_state]
    for i in range(turns):
        assert contents.count(f"问题{i}") == 1
