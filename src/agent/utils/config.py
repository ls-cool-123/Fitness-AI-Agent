# 导入 Pydantic 字段定义工具
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    """Loading the settings with pydantic."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")
    openai_api_type: str = "openai"
    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    openai_api_key: str = ""
    openai_api_version: str = ""
    gemini_api_key: str = ""
    deepseek_api_key: str = ""
    deepseek_api_base: str = "https://api.deepseek.com"
    deepseek_model_name: str = "deepseek-v4-flash"
    qwen_api_key: str = ""
    dashscope_api_key: str = ""
    qwen_embedding_api_base: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    dashscope_embedding_api_base: str = ""

    # Model Configuration
    model_name: str = "gemini/gemini-2.5-flash"
    embedding_provider: str = "google"
    embedding_model_name: str = "gemini-embedding-002"
    embedding_size: int = 768
    embedding_batch_size: int = 0  # 0 = no batching; set to 10 for Qwen/Dashscope limit
    # 本地 fastembed 模型缓存目录（provider=local 时生效，留空则读 FASTEMBED_CACHE_PATH）
    fastembed_cache_dir: str = ""
    # 通用 OpenAI 兼容 embedding 网关（provider=siliconflow 等第三方时用）
    embedding_api_base: str = ""
    embedding_api_key: str = ""

    # Database
    database_url: str = "mysql+aiomysql://root:root@localhost:3306/fitness_agent"
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # Fitness Agent
    fitness_collection_name: str = "fitness_kb"

    # Reranker Configuration
    rerank_provider: str = "bge"  # "bge" / "flashrank" / "siliconflow" / "none"
    # 本地重排模型目录（离线/内网环境用）：留空则按模型名去 HuggingFace 拉取。
    # 可用 scripts/materialize_hf_model.py 把缓存里的模型落成普通目录。
    bge_reranker_path: str = ""
    # 送进重排模型的候选数。粗筛仍按 retrieval_k 拉，但只把前 N 条交给
    # Cross-Encoder——BGE 在 CPU 上重排 40 条要 30 秒以上，15 条能把延迟压到可接受，
    # 而粗筛第 16~40 名本来就很少翻盘（见 scripts/recall_at_k.py 的覆盖率曲线）。
    rerank_candidates: int = 15
    # 远程重排（硅基流动 BAAI/bge-reranker-v2-m3 免费）
    rerank_api_base: str = "https://api.siliconflow.cn/v1"
    rerank_api_key: str = ""
    rerank_api_model: str = "BAAI/bge-reranker-v2-m3"
    rerank_top_k: int = 5
    rerank_score_threshold: float = 0.6  # 重排序分数阈值 (0-1)，低于此分的 chunk 被丢弃；0 关闭过滤

    # Retrieval Configuration
    retrieval_k: int = 40  # Number of documents to retrieve initially
    retrieval_k_retry: int = 100  # Number of documents to retrieve on retry

    # QDRANT
    qdrant_url: str = "http://localhost"
    qdrant_api_key: str | None = Field(default=None, validation_alias=AliasChoices("qdrant_api_key", "qdrant_cloud_api_key"))
    qdrant_port: int = 6333
    qdrant_prefer_grpc: bool = False
    phoenix_collector_endpoint: str = "http://phoenix:4318/v1/traces"
    qdrant_collection_name: str = "default"

    # Long-term Memory
    memory_collection_name: str = "user_memories"
    memory_importance_threshold: float = 0.6
    memory_half_life_days: int = 30
    memory_max_per_extraction: int = 5

    # Conversation Checkpoint（会话状态持久化）
    #
    # memory   —— 进程内，重启即丢，用于单测和没有外部依赖的本地调试
    # sqlite   —— 单文件持久化，不需要额外服务，本地验证"重启续聊"用
    # postgres —— 生产形态，docker-compose 里由 postgres 服务提供
    checkpoint_backend: Literal["memory", "sqlite", "postgres"] = "memory"
    postgres_dsn: str = "postgresql://fitness:fitness@localhost:5432/fitness_agent"
    sqlite_checkpoint_path: str = "data/checkpoints.sqlite"
    # 后端初始化失败时是否降级到 memory：宁可丢持久化也不能让服务起不来
    checkpoint_fallback_to_memory: bool = True
    # 线程闲置多久后清理 checkpoint（天）。持久化之后历史只增不减，必须有回收策略
    checkpoint_ttl_days: int = 30
    # 单个用户最多保留的对话线程数（超出后清理最旧的），防止 conversation_id 被滥用
    checkpoint_max_threads_per_user: int = 20

    # HITL —— 训练记录写入前的人工确认
    # 仅在 LangGraph 线程内生效（Agent 调用路径）；直接调 /workout/add 不走确认
    workout_confirm_enabled: bool = True
    # 训练计划生成前的确认（Agent 调用路径）；人体图直接生成不走确认
    plan_confirm_enabled: bool = True

    # Context Window Management
    #
    # 压缩的驱动力是成本而非容量上限：每轮请求都要把完整历史作为输入重发一次
    # 并按量计费，历史越长每轮越贵。deepseek-v4-flash 总额度 1M、单次输出上限
    # 384K，容量本身宽裕，故下方阈值按「多长的历史值得为它花钱」来定，
    # 不挂靠窗口大小。
    #
    # 单次回复的输出上限。模型侧上限为 384K，这里取 4096 是按中文健身建议的
    # 实际长度定的（常规回答 500~1200 token，含表格的完整周期化计划约 2000）。
    # ReAct 循环中工具调用轮的输出只有几十 token，该值只在生成最终回答时才可能触碰
    llm_max_tokens: int = 4096
    # 近似 token 计数的字符/token 比。默认值 4.0 是按英文调的，
    # 中文约 1~1.5 字符/token，用默认值会低估约 3 倍
    token_chars_per_token: float = 2.0
    # 超过该 token 数时清理旧的工具输出，只保留最近 keep 条。
    # 上一轮检索到的知识片段对下一轮无价值，却会陪着一起计费到对话结束，
    # 清理零成本且不损对话结构，所以这一级设得比较靠前
    context_clear_tools_trigger: int = 60000
    context_clear_tools_keep: int = 3
    # 超过该 token 数时对历史做摘要。纯兜底：按每轮约 2K token 估算
    # （含 RAG 输出的轮次约 3~4K，不含的约 0.5~1K），百轮对话才触及此线；
    # 摘要要额外消耗一次 LLM 调用，不宜作为常规手段
    context_summarize_trigger: int = 200000
    context_summarize_keep_messages: int = 12

    # 文档分块与入库
    # 分隔符必须覆盖中文标点：原配置只有 ["\n\n", "\n", ".", "!"]，
    # 中文正文以"。""！""？"结尾，递归切分会一路退化到按字符硬切。
    chunk_size: int = 750
    chunk_overlap: int = 200
    chunk_separators: list[str] = [
        "\n\n", "\n", "。", "！", "？", "；", "，", ".", "!", "?",
    ]
    # Contextual Retrieval —— 入库前为每个 chunk 生成文档级上下文前缀。
    # 启用后需要为每个 chunk 额外调一次 LLM，只建议在批量摄入时开启。
    contextual_retrieval_enabled: bool = False
    contextual_retrieval_model: str = ""  # 空则复用主对话模型
    contextual_retrieval_max_concurrency: int = 8

    # 本地 BM25 模型目录（离线/内网环境用）
    #
    # Qdrant/bm25 默认从 HuggingFace 下载，无外网时会直接把建集合和检索拖死。
    # 指向一个含 english.txt 的本地目录即可跳过下载（fastembed 的
    # specific_model_path 参数会短路整个 download 流程）。
    bm25_model_path: str = ""


config = Config()
