"""Fitness Agent —— 基于 LangGraph 的 ReAct 智能体，配备健身领域工具集。

构建一个工具调用型 Agent，融合三种能力：
- 个人训练记录（通过工具操作 MySQL）
- 健身知识库（通过 rag_search_tool 检索 Qdrant 向量库）
- LLM 推理（DeepSeek / LiteLLM 作为大脑）
"""

from __future__ import annotations

from functools import partial

from langchain.agents import create_agent
from langchain.agents.middleware import (
    ClearToolUsesEdit,
    ContextEditingMiddleware,
    SummarizationMiddleware,
)
from langchain_core.messages.utils import count_tokens_approximately
from langchain_litellm import ChatLiteLLM
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from loguru import logger

from agent.backend.prompts import CONTEXT_SUMMARY_PROMPT, get_system_prompt
from agent.tools import (
    add_workout_tool,
    analyze_progress_tool,
    create_training_plan_tool,
    query_workout_tool,
    rag_search_tool,
    recall_memories_tool,
    update_training_plan_tool,
)
from agent.utils.config import Config


def _create_llm(cfg: Config, *, streaming: bool = True) -> ChatOpenAI | ChatLiteLLM:
    """创建 LLM 实例，沿用现有的多模型切换模式。

    优先使用 DeepSeek（通过 OpenAI 兼容接口），
    未配置 DeepSeek API Key 时回退到 LiteLLM 统一网关。

    Args:
        cfg: 应用配置。
        streaming: 是否开启流式输出。面向用户的回答需要流式（前端逐字渲染），
            而摘要生成这类内部调用不需要，关掉可省去逐 chunk 组装的开销。
    """
    if cfg.deepseek_api_key:
        # DeepSeek 模式：使用 ChatOpenAI 客户端 + 自定义 base_url
        return ChatOpenAI(
            model=cfg.deepseek_model_name,
            api_key=cfg.deepseek_api_key,
            base_url=cfg.deepseek_api_base,
            streaming=streaming,
            max_tokens=cfg.llm_max_tokens,
        )
    # LiteLLM 回退模式：支持多种模型供应商的统一网关
    return ChatLiteLLM(
        model_name=cfg.model_name,
        streaming=streaming,
        max_tokens=cfg.llm_max_tokens,
    )


def build_fitness_agent(
    cfg: Config | None = None,
    checkpointer: object | None = None,
) -> object:
    """构建并返回 Fitness AI ReAct 智能体。

    Agent 会根据用户意图自动选择合适的工具：
    - add_workout_tool —— 记录训练（写入前会 interrupt 等用户确认）
    - query_workout_tool —— 查询训练历史
    - analyze_progress_tool —— 计算训练进展统计
    - rag_search_tool —— 搜索健身知识库
    - recall_memories_tool —— 召回长期记忆
    - create_training_plan_tool —— 制定训练计划（生成前会 interrupt 等用户确认）
    - update_training_plan_tool —— 修改已有计划里的动作（确认后覆盖原计划）

    Args:
        cfg: 应用配置，为 None 时使用全局 Config 单例。
        checkpointer: 会话状态存储。为 None 时退化为进程内 InMemorySaver
            （单测/无外部依赖场景）。生产路径由 ``main.lifespan`` 注入
            持久化实现（见 ``agent.checkpointing``）。

    Returns:
        编译好的 LangGraph ReAct Agent（Runnable 对象）。
    """
    if cfg is None:
        cfg = Config()

    # 创建 LLM 推理引擎
    llm = _create_llm(cfg)

    # Agent 可调用的工具列表
    tools = [
        add_workout_tool,
        query_workout_tool,
        analyze_progress_tool,
        rag_search_tool,
        recall_memories_tool,
        create_training_plan_tool,
        update_training_plan_tool,
    ]

    # 内存检查点：保存对话历史，支持多轮对话的上下文记忆。
    # 注意这里只是兜底，真正的持久化实现由调用方注入。
    memory = checkpointer if checkpointer is not None else InMemorySaver()

    # 上下文窗口管理，两层递进：
    #
    # 第一层 ContextEditingMiddleware —— 清理旧的工具输出。
    # token 大头是工具返回的 JSON（RAG 检索单次就有 2~3K token），而上一轮检索
    # 到的知识库片段对下一轮问题几乎无价值，属于一次性内容，清掉最划算。
    # recall_memories_tool 例外：长期记忆里的用户目标和偏好跨轮次持续有效。
    # create_training_plan_tool / update_training_plan_tool 也例外：计划结果
    # 跨轮次仍要被引用/总结。
    #
    # 注意该中间件在 wrap_model_call 中硬编码使用 count_tokens_approximately
    # 的默认参数（4.0 字符/token，按英文校准），不接受自定义计数器。中文会被
    # 低估约 2 倍，因此这里的 trigger 按「英文口径」折算，即配置值除以折算比。
    approx_ratio = 4.0 / cfg.token_chars_per_token
    context_editing = ContextEditingMiddleware(
        edits=[
            ClearToolUsesEdit(
                trigger=int(cfg.context_clear_tools_trigger / approx_ratio),
                keep=cfg.context_clear_tools_keep,
                exclude_tools=("recall_memories_tool", "create_training_plan_tool", "update_training_plan_tool"),
            )
        ],
    )

    # 第二层 SummarizationMiddleware —— 兜底摘要。
    # 它走 before_model，比第一层的 wrap_model_call 更早执行，看到的是未清理的
    # 消息，所以阈值要设得高一些，避免在第一层足以解决问题时就抢先触发
    # （摘要要额外花一次 LLM 调用）。
    # 阈值必须用绝对 token 数：走自定义 base_url 的 ChatOpenAI 拿不到 model
    # profile，用 ("fraction", x) 会直接抛 ValueError。
    #
    # 摘要用独立的非流式实例：中间件内部是一次性 ainvoke 拿完整结果，
    # 不需要流式；且独立实例让摘要的 token 消耗在 Phoenix trace 里可单独归因，
    # 不与面向用户的回答混在一起。
    #
    # summary_prompt 换成健身场景的中文版：内置提示词面向编程 Agent，
    # 小节设计（文件改动、待办）与本场景不符，且会遗漏伤病限制等关键信息。
    summarization = SummarizationMiddleware(
        model=_create_llm(cfg, streaming=False),
        trigger=("tokens", cfg.context_summarize_trigger),
        keep=("messages", cfg.context_summarize_keep_messages),
        summary_prompt=CONTEXT_SUMMARY_PROMPT,
        token_counter=partial(
            count_tokens_approximately, chars_per_token=cfg.token_chars_per_token
        ),
    )

    # 创建 ReAct Agent：
    # - system_prompt 定义 Agent 的行为人设和规则
    # - checkpointer 负责在多轮对话间持久化状态
    # - middleware 负责控制上下文窗口大小
    agent = create_agent(
        model=llm,
        tools=tools,
        system_prompt=get_system_prompt(),
        middleware=[summarization, context_editing],
        checkpointer=memory,
    )

    logger.info(
        f"Fitness Agent built with {len(tools)} tools, "
        f"model={cfg.deepseek_model_name if cfg.deepseek_api_key else cfg.model_name}, "
        f"max_tokens={cfg.llm_max_tokens}, "
        f"clear_tools_trigger={cfg.context_clear_tools_trigger}, "
        f"summarize_trigger={cfg.context_summarize_trigger}"
    )
    return agent


# 模块级 Agent 实例 —— 启动时由 main.lifespan 注入（带持久化 checkpointer），
# 未注入时首次访问会惰性构建一个内存版，保证单测/脚本可以直接 import 使用。
# 构建一次后整个应用生命周期复用，避免每次请求重建 LLM 连接和工具定义。
_agent: object | None = None


def set_agent(agent: object) -> None:
    """注入已构建的 Agent（应用启动时调用）。"""
    global _agent
    _agent = agent


def get_agent() -> object:
    """获取当前 Agent 实例，未初始化时惰性构建内存版。"""
    global _agent
    if _agent is None:
        logger.warning(
            "Agent 尚未由 lifespan 初始化，使用内存 checkpointer 惰性构建"
        )
        _agent = build_fitness_agent()
    return _agent
