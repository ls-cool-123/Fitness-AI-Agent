# 导入 Pydantic 字段定义工具
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

    # Database
    database_url: str = "mysql+aiomysql://root:root@localhost:3306/fitness_agent"
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # Fitness Agent
    fitness_collection_name: str = "fitness_kb"

    # Reranker Configuration
    rerank_provider: str = "bge"  # "bge" / "flashrank" / "none"
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


config = Config()
