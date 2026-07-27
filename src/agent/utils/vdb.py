"""Vector Database Utilities.

本模块封装了 Qdrant 向量数据库的连接管理和集合操作。
设计模式：模块级单例 —— Qdrant 客户端在 import 时创建一次，
后续所有调用复用同一个连接，避免重复建立连接的开销。

主要功能：
  1. 模块导入时自动创建同步/异步 Qdrant 客户端单例
  2. 提供 LangChain 级别的 QdrantVectorStore 封装（混合检索）
  3. 集合（collection）的创建与初始化（同步 + 异步）
  4. 批量初始化所有向量数据库
"""

import warnings

import jieba
from langchain_core.embeddings import Embeddings
from langchain_qdrant import FastEmbedSparse, QdrantVectorStore, RetrievalMode
from langchain_qdrant.sparse_embeddings import SparseVector
from loguru import logger
from qdrant_client import AsyncQdrantClient, QdrantClient, models

from agent.utils.config import Config


# ============================================================
# 中文分词 BM25 稀疏嵌入 —— jieba 预处理 + FastEmbedSparse
# ============================================================

class JiebaBM25Sparse:
    """中文感知的 BM25 稀疏嵌入包装器。

    FastEmbedSparse (Qdrant/bm25) 底层使用空格分词，中文没有空格，
    整句被当成一个 token 导致完全无法匹配。

    本包装器在调用 BM25 前先用 jieba 将中文切分为空格分隔的词序列，
    英文/数字直接保留原样，从而让 BM25 能对中文做正确的关键词匹配。
    """

    def __init__(self, model_name: str = "Qdrant/bm25"):
        self._inner = FastEmbedSparse(model_name=model_name)

    @staticmethod
    def _segment(text: str) -> str:
        """对中文做分词后用空格连接，英文/数字原样保留。"""
        return " ".join(jieba.cut(text))

    def embed_query(self, text: str) -> SparseVector:
        """对单条查询做分词 → BM25 稀疏向量。"""
        return self._inner.embed_query(self._segment(text))

    def embed_documents(self, texts: list[str]) -> list[SparseVector]:
        """对多篇文档做分词 → BM25 稀疏向量列表。"""
        return self._inner.embed_documents([self._segment(t) for t in texts])

    def embed_text(self, text: str) -> SparseVector:
        """别名——对单条文本分词后生成稀疏向量。"""
        return self._inner.embed_query(self._segment(text))


# ============================================================
# 模块级单例：在 import 时初始化，整个应用生命周期内复用
# ============================================================

# BM25 稀疏嵌入模型 —— 用于混合检索中的关键词匹配
# 使用 jieba 预处理中文文本，解决 FastEmbedSparse 对中文无效的问题
sparse_embeddings = JiebaBM25Sparse(model_name="Qdrant/bm25")

# 从配置中读取 Qdrant 连接参数
settings = Config()

# ---- 同步 Qdrant 客户端 ----
# 抑制 HTTP + API Key 组合时触发的 "insecure connection" UserWarning
with warnings.catch_warnings():
    warnings.filterwarnings("ignore", category=UserWarning, message="Api key is used with an insecure connection")
    qdrant_client = QdrantClient(
        location=settings.qdrant_url,          # Qdrant 服务地址
        port=settings.qdrant_port,             # Qdrant 服务端口
        api_key=settings.qdrant_api_key,       # API 认证密钥
        prefer_grpc=settings.qdrant_prefer_grpc,  # 是否优先使用 gRPC 协议
    )

# ---- 异步 Qdrant 客户端 ----
# 同样抑制 insecure connection 警告
with warnings.catch_warnings():
    warnings.filterwarnings("ignore", category=UserWarning, message="Api key is used with an insecure connection")
    async_qdrant_client = AsyncQdrantClient(
        location=settings.qdrant_url,
        port=settings.qdrant_port,
        api_key=settings.qdrant_api_key,
        prefer_grpc=settings.qdrant_prefer_grpc,
    )


# ============================================================
# LangChain VectorStore 封装
# ============================================================

def init_vdb(collection_name: str, embedding: Embeddings) -> QdrantVectorStore:
    """建立与 Qdrant DB 的连接并返回 LangChain VectorStore 实例。

    使用混合检索模式（HYBRID），同时结合：
      - 稠密向量（dense embedding）的语义相似度匹配
      - BM25 稀疏向量（sparse vector）的关键词匹配

    Args:
        collection_name (str): Qdrant 中的集合名称。
        embedding (Embeddings): 稠密嵌入模型实例。

    Returns:
        QdrantVectorStore: 已配置好的向量存储实例，可直接用于 RAG 检索链。

    """
    logger.info(f"USING COLLECTION: {collection_name}")

    # 构建 LangChain 的 QdrantVectorStore，配置混合检索
    vector_db = QdrantVectorStore(
        client=qdrant_client,                 # 复用模块级同步客户端
        collection_name=collection_name,       # 目标集合
        embedding=embedding,                   # 稠密嵌入模型
        sparse_embedding=sparse_embeddings,    # 稀疏嵌入模型（BM25）
        retrieval_mode=RetrievalMode.HYBRID,   # 混合检索：稠密 + 稀疏
        sparse_vector_name="fast-sparse-bm25", # Qdrant 中稀疏向量的字段名
    )
    logger.info("SUCCESS: Qdrant DB initialized.")

    return vector_db


# ============================================================
# 客户端单例访问函数
# ============================================================

def load_vec_db_conn() -> QdrantClient:
    """返回模块级同步 QdrantClient 单例。

    Returns:
        QdrantClient: 共享的同步 QdrantClient 实例。

    """
    return qdrant_client


def get_async_qdrant_client() -> AsyncQdrantClient:
    """返回模块级异步 QdrantClient 单例。

    Returns:
        AsyncQdrantClient: 共享的 AsyncQdrantClient 实例。

    """
    return async_qdrant_client


# ============================================================
# 集合（Collection）的初始化 —— 同步版本
# ============================================================

def initialize_vector_db(collection_name: str, embeddings_size: int) -> None:
    """初始化指定集合，如果不存在则创建。

    这是启动时的初始化入口 —— 幂等操作：集合已存在则跳过。

    Args:
        collection_name (str): 集合名称。
        embeddings_size (int): 稠密向量的维度。

    """
    client = load_vec_db_conn()
    # 幂等检查：集合已存在则无需重复创建
    if client.collection_exists(collection_name=collection_name):
        logger.info(f"SUCCESS: Collection {collection_name} already exists.")
    else:
        # 集合不存在，执行创建流程
        generate_collection(collection_name=collection_name, embeddings_size=embeddings_size)


def generate_collection(collection_name: str, embeddings_size: int) -> None:
    """创建 Qdrant 集合，同时配置稠密和稀疏向量。

    集合配置：
      - 稠密向量：维度 = embeddings_size，距离度量 = 余弦距离（COSINE）
      - 稀疏向量：使用 Qdrant/bm25 模型生成的 BM25 稀疏向量

    Args:
        collection_name (str): 集合名称。
        embeddings_size (int): 稠密向量的维度（取决于使用的嵌入模型）。

    """
    client = load_vec_db_conn()
    # 设置稀疏嵌入模型（BM25），使 Qdrant 内部能处理稀疏向量
    client.set_sparse_model(embedding_model_name="Qdrant/bm25")
    # 创建集合：同时定义稠密向量配置和稀疏向量配置
    client.create_collection(
        collection_name=collection_name,
        vectors_config=models.VectorParams(
            size=embeddings_size,            # 稠密向量维度
            distance=models.Distance.COSINE,  # 余弦相似度
        ),
        sparse_vectors_config=client.get_fastembed_sparse_vector_params(),  # BM25 稀疏向量参数
    )
    logger.info(f"SUCCESS: Collection {collection_name} created.")


# ============================================================
# 集合（Collection）的初始化 —— 异步版本
# 用于 async event loop 中的初始化场景
# ============================================================

async def initialize_vector_db_async(collection_name: str, embeddings_size: int) -> None:
    """异步版 initialize_vector_db。

    Args:
        collection_name (str): 集合名称。
        embeddings_size (int): 稠密向量的维度。

    """
    client = get_async_qdrant_client()
    # 幂等检查：集合已存在则跳过
    if await client.collection_exists(collection_name=collection_name):
        logger.info(f"SUCCESS: Collection {collection_name} already exists.")
    else:
        await generate_collection_async(collection_name=collection_name, embeddings_size=embeddings_size)


async def generate_collection_async(collection_name: str, embeddings_size: int) -> None:
    """异步版 generate_collection。

    Args:
        collection_name (str): 集合名称。
        embeddings_size (int): 稠密向量的维度。

    """
    client = get_async_qdrant_client()
    # 设置稀疏嵌入模型
    client.set_sparse_model(embedding_model_name="Qdrant/bm25")
    # 异步创建集合
    await client.create_collection(
        collection_name=collection_name,
        vectors_config=models.VectorParams(size=embeddings_size, distance=models.Distance.COSINE),
        sparse_vectors_config=client.get_fastembed_sparse_vector_params(),
    )
    logger.info(f"SUCCESS: Collection {collection_name} created.")


# ============================================================
# 批量初始化所有向量数据库
# ============================================================

def initialize_all_vector_dbs(config: Config) -> None:
    """应用启动时一次性初始化所有需要的 Qdrant 集合。确保应用启动时，哪些 Qdrant 集合需要确保存在

    初始化策略：
      1. 始终初始化主集合（qdrant_collection_name）
      2. 如果配置了健身知识库集合且与主集合名称不同，也一并初始化

    Args:
        config (Config): 应用配置对象，包含集合名称和嵌入维度。

    """
    # 初始化主 RAG 集合
    initialize_vector_db(
        collection_name=config.qdrant_collection_name,
        embeddings_size=config.embedding_size,
    )
    # 如果配置了独立的健身知识库集合，也初始化它
    if config.fitness_collection_name and config.fitness_collection_name != config.qdrant_collection_name:
        initialize_vector_db(
            collection_name=config.fitness_collection_name,
            embeddings_size=config.embedding_size,
        )
    # 初始化用户长期记忆集合
    initialize_vector_db(
        collection_name=config.memory_collection_name,
        embeddings_size=config.embedding_size,
    )
