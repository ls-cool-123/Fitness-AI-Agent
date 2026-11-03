"""Embedding 模型工具模块。

该模块根据配置文件(Config)中指定的 embedding_provider，
动态创建并返回对应的 Embedding 模型实例。

支持：
- Google Gemini
- OpenAI
- 通义千问（Qwen）
- DashScope
- local：本地 fastembed 模型（不联网、免费，适合离线/内网/零成本场景）
"""

# LangChain 中所有 Embedding 模型的统一父类
from langchain_core.embeddings import Embeddings

# 项目的配置类，保存各种 API Key、模型名称等配置
from agent.utils.config import Config


def get_embedding_model(cfg: Config) -> Embeddings:
    """
    根据配置返回对应的 Embedding 模型对象。

    参数：
        cfg: 项目配置对象(Config)

    返回：
        一个实现了 LangChain Embeddings 接口的实例。

    例如：
        GoogleGenerativeAIEmbeddings
        OpenAIEmbeddings
    """

    # 获取当前配置的 Embedding 提供商
    # 例如："openai"、"google"
    provider = cfg.embedding_provider

    # 获取具体使用的 Embedding 模型名称
    # 例如：
    # text-embedding-3-small
    # text-embedding-3-large
    model_name = cfg.embedding_model_name

    # Python 3.10+ 的 match-case，相当于 switch-case
    match provider:

        # ==============================
        # Google Gemini Embedding
        # ==============================
        case "google":

            try:
                from langchain_google_genai import (
                    GoogleGenerativeAIEmbeddings,
                )  # noqa: PLC0415

            # 如果没有安装依赖，则提示用户安装
            except ImportError as exc:
                msg = "langchain-google-genai is required for Google embeddings."
                raise ImportError(msg) from exc

            # 创建 Google Embedding 模型
            return GoogleGenerativeAIEmbeddings(
                model=model_name,

                # Gemini API Key
                google_api_key=cfg.gemini_api_key or None,

                # 输出向量维度
                output_dimensionality=cfg.embedding_size,
            )

        # ==============================
        # OpenAI Embedding
        # ==============================
        case "openai":

            from langchain_openai import OpenAIEmbeddings  # noqa: PLC0415

            # 创建 OpenAI Embedding 模型
            return OpenAIEmbeddings(
                model=model_name,

                # OpenAI API Key
                api_key=cfg.openai_api_key or None,
            )

        # ==============================
        # 通义千问 / DashScope Embedding
        # ==============================
        #
        # 阿里云兼容 OpenAI API，
        # 所以直接复用 OpenAIEmbeddings。
        #
        case "qwen" | "dashscope":

            from langchain_openai import OpenAIEmbeddings  # noqa: PLC0415

            return OpenAIEmbeddings(
                model=model_name,

                # 优先使用 qwen_api_key
                # 没有则使用 dashscope_api_key
                api_key=cfg.qwen_api_key or cfg.dashscope_api_key or None,

                # 指定兼容 OpenAI 的 Base URL
                base_url=(
                    cfg.qwen_embedding_api_base
                    or cfg.dashscope_embedding_api_base
                    or "https://dashscope.aliyuncs.com/compatible-mode/v1"
                ),

                # 指定输出向量维度
                dimensions=cfg.embedding_size,

                # 不检查文本长度限制
                check_embedding_ctx_length=False,
            )

        # ==============================
        # 第三方 OpenAI 兼容网关（硅基流动等）
        # ==============================
        #
        # 硅基流动的 BAAI/bge-m3、bge-large-zh-v1.5 是免费模型，
        # 接口与 OpenAI 兼容，换 base_url 即可，适合替代收费的 DashScope。
        # 注意不要传 dimensions：非 OpenAI 官方端点普遍不支持该参数。
        case "siliconflow" | "thirdparty":

            from langchain_openai import OpenAIEmbeddings  # noqa: PLC0415

            base_url = cfg.embedding_api_base or "https://api.siliconflow.cn/v1"
            api_key = cfg.embedding_api_key or cfg.openai_api_key or None
            if not api_key:
                msg = "EMBEDDING_API_KEY 未配置，无法调用第三方 embedding 网关。"
                raise ValueError(msg)

            return OpenAIEmbeddings(
                model=model_name,
                api_key=api_key,
                base_url=base_url,
                check_embedding_ctx_length=False,
            )

        # ==============================
        # 本地 fastembed（ONNX，不依赖 torch）
        # ==============================
        #
        # 免费、离线可跑，适合零成本/内网环境。中文推荐：
        #   BAAI/bge-small-zh-v1.5（512 维，~95 MB）
        #   jinaai/jina-embeddings-v2-base-zh（768 维，更长上下文）
        # 注意：换 embedding 模型后维度会变，已有集合必须重建。
        case "local" | "fastembed":

            try:
                from langchain_community.embeddings import (
                    FastEmbedEmbeddings,
                )  # noqa: PLC0415

            except ImportError as exc:
                msg = "fastembed is required for local embeddings."
                raise ImportError(msg) from exc

            # cache_dir 留空时 fastembed 自己读 FASTEMBED_CACHE_PATH 环境变量
            return FastEmbedEmbeddings(
                model_name=model_name,
                cache_dir=cfg.fastembed_cache_dir or None,
            )

        # ==============================
        # 未配置支持的 Provider
        # ==============================
        case _:

            msg = "No suitable embedding Model configured!"

            raise KeyError(msg)