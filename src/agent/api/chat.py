"""健身 AI 助手聊天接口。

提供四个端点：
- POST /chat         : 非流式问答，等待完整结果后返回。
- POST /chat/stream  : 流式问答，实时推送工具调用状态和生成内容。
- POST /chat/confirm : 恢复被 interrupt() 挂起的训练记录写入，带用户确认结果。
- POST /chat/reset   : 清空某个对话线程的 checkpoint。

线程模型：``thread_id = "{user_id}:{conversation_id}"``。早期版本直接用
user_id 当线程 id，在 MemorySaver 下靠"重启即清空"被动兜底；换成持久化
checkpointer 后，同一线程会无限累积历史，因此必须按对话分线程。
"""

import asyncio
import json
from collections.abc import AsyncGenerator

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langgraph.types import Command
from loguru import logger
from pydantic import BaseModel, Field

from agent.agent.fitness_agent import get_agent
from agent.memory import extract_and_store_memories
from agent.tools import current_user_id

router = APIRouter()

# rag_search_tool 一次返回 5 个 chunk，每个 content 可能上千字。原样推送会让流
# 膨胀好几倍，而前端的来源卡片只需要够判断相关性的开头部分。
_RAG_CONTENT_LIMIT = 300

# 未显式传 conversation_id 时使用的默认对话
_DEFAULT_CONVERSATION = "default"

# 同一线程的确认请求串行化，避免并发重复 resume 导致重复落库
_confirm_locks: dict[str, asyncio.Lock] = {}


def _shrink(tool_name: str, result):
    """裁剪工具结果中体积过大的字段，供流式推送使用。

    只处理 rag_search_tool 的 content（截断到 300 字符），source/category/score
    等元数据原样保留。其余工具的结果本身就很小，直接返回。

    Args:
        tool_name: 工具名称。
        result: 已解析的工具结果（dict / list / None）。

    Returns:
        可直接序列化的结果，体积受控。
    """
    if tool_name != "rag_search_tool" or not isinstance(result, list):
        return result

    shrunk = []
    for chunk in result:
        if not isinstance(chunk, dict):
            shrunk.append(chunk)
            continue
        content = chunk.get("content")
        if isinstance(content, str) and len(content) > _RAG_CONTENT_LIMIT:
            chunk = {**chunk, "content": content[:_RAG_CONTENT_LIMIT] + "..."}
        shrunk.append(chunk)
    return shrunk


def _escape_thread_part(value: str) -> str:
    """转义 thread_id 分隔符，保证拼接结果可逆、不会串号。

    用户 id 理论上可能是任意字符串（后端既接受 UUID 也接受用户名），
    如果各自自带冒号，``a:b`` + ``c`` 与 ``a`` + ``b:c`` 会拼成同一个
    thread_id，两个用户就会共享上下文。转义后这类碰撞不可能发生。
    """
    return value.replace("%", "%25").replace(":", "%3A")


def _resolve_thread_id(user_id: str, conversation_id: str | None) -> str:
    """拼出 LangGraph 的 thread_id：用户 + 对话维度。

    用 ``:`` 分隔而不是嵌套结构，是因为 thread_id 必须是字符串，且要能一眼
    看出归属。conversation_id 为空时落到兜底线程，兼容未升级的前端。

    Args:
        user_id: 用户标识（UUID 或用户名）。
        conversation_id: 前端维护的对话标识，可为 None。

    Returns:
        形如 ``"u-1:default"`` 的线程 id。
    """
    conversation = conversation_id or _DEFAULT_CONVERSATION
    return f"{_escape_thread_part(user_id)}:{_escape_thread_part(conversation)}"


class ChatMessage(BaseModel):
    """单条对话消息，对应 OpenAI 消息格式的子集。"""
    role: str = Field(description="消息角色：'user' 或 'assistant'")
    content: str = Field(description="消息文本内容")


class ChatRequest(BaseModel):
    """聊天请求体，包含对话历史和用户标识。"""
    messages: list[ChatMessage] = Field(description="对话历史（含当前用户消息）")
    user_id: str = Field(description="用户 UUID，用于数据隔离和鉴权")
    collection_name: str = Field(default="fitness_kb", description="RAG 检索用的 Qdrant 集合名称")
    conversation_id: str | None = Field(
        default=None,
        description="对话线程标识。同一用户的不同对话应传不同值；为空时使用默认线程",
    )


class ChatResponse(BaseModel):
    """非流式聊天的响应体。"""
    answer: str = Field(description="Agent 的最终回答文本")
    interrupt: dict | None = Field(
        default=None,
        description="存在待人工确认的操作时返回，前端应弹出确认卡片而非直接展示 answer",
    )


class ConfirmRequest(BaseModel):
    """人工确认请求 —— 恢复被 interrupt() 挂起的写入操作。"""
    user_id: str = Field(description="用户 UUID，必须与发起对话时一致")
    conversation_id: str | None = Field(default=None, description="对话线程标识")
    approved: bool = Field(default=True, description="是否同意本次写入")
    edits: list[dict] | None = Field(
        default=None,
        description=(
            "用户在确认卡片里修正后的数据。训练记录是动作数值列表；"
            "训练计划是 [{slot_id, exercise_name}] 换动作列表。为空则使用 Agent 原值"
        ),
    )


def _to_langchain_messages(messages: list[ChatMessage]) -> list[AnyMessage]:
    """将前端消息格式转换为 LangChain 标准消息格式。"""
    converted: list[AnyMessage] = []
    for msg in messages:
        if msg.role == "user":
            converted.append(HumanMessage(content=msg.content))
        elif msg.role == "assistant":
            converted.append(AIMessage(content=msg.content))
    return converted


def _thread_config(user_id: str, conversation_id: str | None) -> dict:
    """构造 LangGraph 的 runnable config。"""
    return {"configurable": {"thread_id": _resolve_thread_id(user_id, conversation_id)}}


async def _build_agent_input(request: ChatRequest) -> list[AnyMessage]:
    """构建本轮要交给 Agent 的**增量**消息。

    对话历史的所有权归 checkpointer，而非前端。前端每轮都会重发全量历史，
    若原样转发，这些消息因为不带 id 会被 add_messages 分配新 UUID，与
    checkpointer 中已有的消息匹配不上，从而被当作新消息追加——消息数会按
    O(N²) 膨胀，同一段对话被重复喂给 LLM 多次。

    因此这里按线程状态分两种情况：
    - 线程已有历史 → 只追加最新一条用户消息，其余交给 checkpointer。
    - 线程为空（首轮，或换了新的 conversation_id）→ 用前端历史重建对话，
      并注入带 user_id 的 SystemMessage。

    Args:
        request: 聊天请求，含前端维护的全量对话历史。

    Returns:
        本轮传给 Agent 的消息列表。
    """
    agent = get_agent()
    state = await agent.aget_state(_thread_config(request.user_id, request.conversation_id))
    thread_is_empty = not state.values.get("messages")

    if not thread_is_empty:
        # 已有历史：只发最新一条用户消息，避免重复累积
        latest_user = next(
            (m for m in reversed(request.messages) if m.role == "user"), None
        )
        return [HumanMessage(content=latest_user.content)] if latest_user else []

    # 线程为空：注入 user_id 后用前端历史重建对话
    system_message = SystemMessage(
        content=f"当前用户的 user_id 是: {request.user_id}。"
        f"调用任何工具时都必须使用这个 user_id。"
    )
    return [system_message, *_to_langchain_messages(request.messages)]


def _interrupts_from_state(state) -> list[dict]:
    """从线程快照里取出待处理的中断。

    LangGraph 把 ``interrupt()`` 的载荷挂在 ``state.tasks[*].interrupts`` 上，
    只有存在中断的线程才能被 resume。
    """
    pending: list[dict] = []
    for task in getattr(state, "tasks", ()) or ():
        for interrupt_obj in getattr(task, "interrupts", ()) or ():
            pending.append(
                {
                    "id": getattr(interrupt_obj, "id", None),
                    "value": getattr(interrupt_obj, "value", None),
                }
            )
    return pending


def _interrupts_from_result(result) -> list[dict]:
    """从 ainvoke 的返回值里取出中断载荷（``__interrupt__`` 键）。"""
    if not isinstance(result, dict):
        return []
    raw = result.get("__interrupt__")
    if not raw:
        return []
    items = raw if isinstance(raw, (list, tuple)) else [raw]
    return [
        {"id": getattr(item, "id", None), "value": getattr(item, "value", None)}
        for item in items
    ]


def _final_answer(result) -> str:
    """取最后一条 AI 文本作为回答；被中断时可能没有 AI 消息。"""
    messages = result.get("messages") if isinstance(result, dict) else None
    if not messages:
        return ""
    for message in reversed(messages):
        content = getattr(message, "content", "")
        if content:
            return content
    return ""


def _pending_guidance(pending: list[dict]) -> str:
    """线程有未确认操作时，告诉用户应该去卡片里操作。

    不能在线程 interrupt 期间继续 ainvoke/astream_events：Agent 在等
    ``Command(resume=...)``，新消息没有可消费的执行路径，界面会一直停在
    「思考中」。这里统一拦成一段可读提示。
    """
    value = pending[0].get("value") if pending else None
    action = value.get("action") if isinstance(value, dict) else None
    if action == "confirm_plan":
        return (
            "当前有一个待确认的训练计划。请在上方的计划卡片中直接下拉替换动作，"
            "或点「取消」后再重新生成；确认前不需要在对话里告诉我换哪个动作。"
        )
    if action == "confirm_workout":
        return "当前有一个待确认的训练记录。请先在上方卡片里确认或取消，再继续对话。"
    return "当前有一个待确认操作。请先在上方卡片里确认或取消，再继续对话。"


@router.post("", tags=["chat"], summary="Chat with the Fitness AI Agent")
async def chat(request: ChatRequest) -> ChatResponse:
    """向 Fitness AI Agent 发送消息（非流式）。

    Agent 自动决定调用哪些工具：记录训练、查询训练历史、分析进展、搜索健身
    知识、召回长期记忆。若某次工具调用触发了人工确认，响应里会带
    ``interrupt`` 字段，前端应改为渲染确认卡片。
    """
    agent = get_agent()
    config = _thread_config(request.user_id, request.conversation_id)

    # 线程里还有未确认操作时，普通聊天不能继续：Agent 正在等 Command(resume)。
    # 直接拦成提示，避免 ainvoke 停在 interrupt 上、界面一直「思考中」。
    state = await agent.aget_state(config)
    pending_state = _interrupts_from_state(state)
    if pending_state:
        logger.info(f"Chat blocked by pending interrupt: {len(pending_state)}")
        return ChatResponse(answer=_pending_guidance(pending_state), interrupt=pending_state[0])

    # 构建本轮增量消息（历史由 checkpointer 持有，不重复转发）
    agent_input = await _build_agent_input(request)

    logger.info(f"Chat request: thread={config['configurable']['thread_id']}, new_messages={len(agent_input)}")

    # 设置上下文变量，强制本次调用内所有工具使用正确的 user_id。
    # 这是防止 LLM 幻觉出其他用户 ID 的安全机制。
    token = current_user_id.set(request.user_id)
    try:
        result = await agent.ainvoke({"messages": agent_input}, config=config)
    finally:
        # 无论成功或异常，调用结束后必须重置上下文变量
        current_user_id.reset(token)

    pending = _interrupts_from_result(result)
    answer = _final_answer(result)

    # 异步提取长期记忆（fire-and-forget，不阻塞响应）。
    # 被中断时不提取：这轮对话还没真正结束。
    if not pending:
        asyncio.create_task(
            extract_and_store_memories(
                user_id=request.user_id,
                langchain_messages=_to_langchain_messages(request.messages),
            )
        )

    if pending:
        logger.info(f"Chat paused for confirmation: {len(pending)} interrupt(s)")
        return ChatResponse(answer=answer, interrupt=pending[0])

    logger.info(f"Chat response: {answer[:100]}...")
    return ChatResponse(answer=answer)


@router.post("/stream", tags=["chat"], summary="流式问答：实时推送工具调用状态和生成内容")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    """发送消息给健身 AI 助手，通过 NDJSON 流式返回进度和回答。

    每行一个 JSON 对象，type 字段区分消息类型：
    - "status"    : 阶段状态（开始分析 → 工具调用中 → 生成回答 → 完成）
    - "content"   : 逐 token 流式返回的回答文本（前端可逐字渲染）
    - "tool"      : 工具调用详情（工具名、参数、结果预览，以及完整结果 result）
    - "interrupt" : 需要用户确认的操作（训练记录写入前的 HITL 暂停点）
    """
    agent = get_agent()
    config = _thread_config(request.user_id, request.conversation_id)

    # 与 /chat 一致：有未确认操作时不再启动新的 Agent 运行。
    state = await agent.aget_state(config)
    pending_state = _interrupts_from_state(state)
    if pending_state:
        guidance = _pending_guidance(pending_state)
        logger.info(f"Chat stream blocked by pending interrupt: {len(pending_state)}")

        async def pending_stream() -> AsyncGenerator:
            yield json.dumps({"type": "status", "data": "正在分析问题..."}, ensure_ascii=False) + "\n"
            yield json.dumps({"type": "content", "data": guidance}, ensure_ascii=False) + "\n"
            yield json.dumps({"type": "status", "data": "完成"}, ensure_ascii=False) + "\n"

        return StreamingResponse(pending_stream(), media_type="application/x-ndjson")

    # 构建本轮增量消息（逻辑与 /chat 端点一致）
    agent_input = await _build_agent_input(request)

    async def stream() -> AsyncGenerator:
        """内部异步生成器，逐事件产出 NDJSON 行。

        利用 LangGraph 的 astream_events(v2) 订阅 Agent 内部运行事件，
        将每个事件实时序列化为 NDJSON 行推送给前端。
        """
        # 阶段 1: 分析阶段开始
        yield json.dumps({"type": "status", "data": "正在分析问题..."}, ensure_ascii=False) + "\n"

        # 设置上下文变量，强制工具使用正确的 user_id
        token = current_user_id.set(request.user_id)
        try:
            async for event in agent.astream_events(
                {"messages": agent_input},
                config=config,
                version="v2",  # v2 版本事件更详细，支持 on_tool_start/end 等细粒度事件
            ):
                kind = event["event"]
                name = event.get("name", "")

                # ---- 工具调用开始 ----
                if kind == "on_tool_start":
                    tool_name = name
                    tool_input = event["data"].get("input", {})
                    # 裁剪过长的输入（如 5000 字的查询），避免流式传输膨胀
                    safe_input = {k: (v[:200] + "..." if isinstance(v, str) and len(v) > 200 else v) for k, v in tool_input.items()}
                    yield json.dumps(
                        {"type": "tool", "data": {"tool": tool_name, "input": safe_input, "status": "start"}},
                        ensure_ascii=False,
                    ) + "\n"

                # ---- 工具调用完成 ----
                elif kind == "on_tool_end":
                    tool_output = event["data"].get("output", "")
                    # 只传递结果的前 100 个字符作为预览，完整结果由 LLM 处理后输出
                    preview = tool_output[:100] + "..." if isinstance(tool_output, str) and len(tool_output) > 100 else str(tool_output)[:100]
                    # v2 事件里 output 通常是 ToolMessage 对象而非裸字符串，
                    # 真正的 JSON 文本在 .content 上。
                    text = tool_output.content if hasattr(tool_output, "content") else tool_output
                    try:
                        result = json.loads(text) if isinstance(text, str) else None
                    except json.JSONDecodeError:
                        # 非 JSON 输出（如工具内部异常字符串）不推送结构化结果，
                        # 前端跳过卡片渲染，LLM 的文字回答本身已覆盖内容。
                        result = None
                    yield json.dumps(
                        {
                            "type": "tool",
                            "data": {
                                "tool": name,
                                "output_preview": preview,
                                "status": "end",
                                "result": _shrink(name, result),
                            },
                        },
                        ensure_ascii=False,
                    ) + "\n"

                # ---- LLM 开始生成回答文本 ----
                elif kind == "on_chat_model_start":
                    yield json.dumps({"type": "status", "data": "正在生成回答..."}, ensure_ascii=False) + "\n"

                # ---- 逐 token 流式输出回答内容 ----
                elif kind == "on_chat_model_stream":
                    content = event["data"]["chunk"].content
                    if content:
                        yield json.dumps({"type": "content", "data": content}, ensure_ascii=False) + "\n"

        finally:
            # 无论成功或异常，调用结束后必须重置上下文变量
            current_user_id.reset(token)

        # 流结束后检查是否停在人工确认点：interrupt 不抛异常，需要主动查状态
        state = await agent.aget_state(config)
        pending = _interrupts_from_state(state)
        if pending:
            payload = dict(pending[0])
            payload["thread_id"] = config["configurable"]["thread_id"]
            yield json.dumps(
                {"type": "interrupt", "data": payload}, ensure_ascii=False
            ) + "\n"
            yield json.dumps({"type": "status", "data": "等待确认"}, ensure_ascii=False) + "\n"
            return

        # 阶段 5: 流结束信号
        yield json.dumps({"type": "status", "data": "完成"}, ensure_ascii=False) + "\n"

        # 异步提取长期记忆（fire-and-forget，不阻塞响应）
        asyncio.create_task(
            extract_and_store_memories(
                user_id=request.user_id,
                langchain_messages=_to_langchain_messages(request.messages),
            )
        )

    return StreamingResponse(stream(), media_type="application/x-ndjson")


@router.post("/confirm", tags=["chat"], summary="确认或取消待写入的训练记录/训练计划")
async def confirm(request: ConfirmRequest) -> ChatResponse:
    """恢复被 interrupt() 挂起的 Agent 执行。

    目前有两类挂起操作共用本接口，靠 interrupt 载荷里的 ``action`` 区分：
    - ``confirm_workout``：``add_workout_tool`` 写库前暂停，edits 是动作数值；
    - ``confirm_plan``：``create_training_plan_tool`` 保存前暂停，edits 是
      ``[{slot_id, exercise_name}]`` 换动作列表。

    本接口用 ``Command(resume=...)`` 从断点继续：

    - 同意且带 edits → 用用户修正后的数据落库
    - 同意无 edits   → 用 Agent 解析的原值落库
    - 不同意         → 工具直接返回 cancelled，不写库

    线程不存在待确认任务时返回 409，避免重复点击导致重复写入。
    """
    agent = get_agent()
    thread_id = _resolve_thread_id(request.user_id, request.conversation_id)
    config = {"configurable": {"thread_id": thread_id}}
    lock = _confirm_locks.setdefault(thread_id, asyncio.Lock())

    async with lock:
        state = await agent.aget_state(config)
        if not _interrupts_from_state(state):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="当前对话没有待确认的操作，可能已处理或已过期。",
            )

        token = current_user_id.set(request.user_id)
        try:
            result = await agent.ainvoke(
                Command(resume={"approved": request.approved, "edits": request.edits}),
                config=config,
            )
        finally:
            current_user_id.reset(token)

    pending = _interrupts_from_result(result)
    if pending:
        # 极端情况下工具里还有第二个确认点，继续交回前端
        return ChatResponse(answer=_final_answer(result), interrupt=pending[0])

    return ChatResponse(answer=_final_answer(result))


@router.post("/reset", tags=["chat"], summary="清空某个对话线程的上下文")
async def reset(request: ChatRequest) -> dict:
    """删除线程的 checkpoint 历史。

    持久化之后历史不会自己消失，需要一个显式的新建会话入口；前端"新对话"
    按钮应当换成新的 conversation_id，或调用本接口清空当前线程。
    """
    agent = get_agent()
    thread_id = _resolve_thread_id(request.user_id, request.conversation_id)
    saver = getattr(agent, "checkpointer", None)
    delete = getattr(saver, "adelete_thread", None)
    if delete is None:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="当前 checkpointer 不支持删除线程。",
        )
    await delete(thread_id)
    logger.info(f"Thread reset: {thread_id}")
    return {"status": "ok", "thread_id": thread_id}
