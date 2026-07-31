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
    # 模型上下文窗口大小，换模型时需同步调整
    model_context_window: int = 65536
    # 单次回复的输出上限。ReAct 循环中工具调用轮的输出只有几十 token，
    # 该值实际只在生成最终回答时才可能触碰
    llm_max_tokens: int = 4096
    # 近似 token 计数的字符/token 比。默认值 4.0 是按英文调的，
    # 中文约 1~1.5 字符/token，用默认值会低估约 3 倍
    token_chars_per_token: float = 2.0
    # 超过该 token 数时清理旧的工具输出，只保留最近 keep 条
    context_clear_tools_trigger: int = 20000
    context_clear_tools_keep: int = 3
    # 超过该 token 数时对历史做摘要（兜底，会额外消耗一次 LLM 调用）
    context_summarize_trigger: int = 36000
    context_summarize_keep_messages: int = 12


config = Config()
