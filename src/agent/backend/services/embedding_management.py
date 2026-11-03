"""文档嵌入管理服务。

负责文档嵌入到向量数据库的完整流程：
从磁盘加载文档 → 分割为文本块 →（可选）生成上下文前缀 → 生成嵌入向量 → 存入 Qdrant。

两个容易踩的坑，本模块都做了处理：

1. **中文分块**：``RecursiveCharacterTextSplitter`` 的分隔符原先是
   ``["\\n\\n", "\\n", ".", "!"]``，全是英文标点。中文正文以"。""！""？"结尾，
   递归切分会一路退化到按字符硬切，chunk 边界落在句子中间，指代大量丢失。
2. **Contextual Retrieval**：即便分块正确，一个 chunk 脱离原文后也常常
   没有主语（"该动作""此阶段"）。入库前用 LLM 为每个 chunk 生成一句文档级
   上下文并拼到正文前，稠密和 BM25 两路都能因此受益。
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain_community.document_loaders import DirectoryLoader, PyPDFium2Loader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from loguru import logger

from agent.utils.config import config
from agent.utils.embeddings import get_embedding_model
from agent.utils.vdb import init_vdb, initialize_vector_db

load_dotenv()

# 生成上下文前缀时最多把原文前多少字符喂给 LLM。
# 太短拿不到全局信息，太长则每个 chunk 都要重复付一次长文档的钱。
_CONTEXT_DOC_CHARS = 6000

# 上下文前缀的提示词。要点：只允许引用原文信息（防幻觉），限制长度（防 chunk 膨胀）。
_CONTEXT_PROMPT = """下面是健身知识库中的一篇文档，以及其中一个片段。
请用 1–2 句中文说明这个片段在文档中的位置与主题，用于提升检索召回。
规则：
- 只使用文档中出现的信息，不要推测或补充常识；
- 不要复述片段原文；
- 不超过 60 字，直接输出说明文字，不要任何前缀。

<文档>
{doc}
</文档>

<片段>
{chunk}
</片段>
"""


class EmbeddingManagement:
    """管理文档嵌入和向量数据库操作。

    职责包括：
    - 连接到 Qdrant 向量数据库并指定集合（collection）。
    - 从目录加载文档并分割为文本块（支持 .pdf / .txt / .md 格式）。
    - 批量生成嵌入向量并存入向量数据库。
    - 在向量数据库中创建新的集合。

    Attributes
    ----------
    cfg : Config
        应用配置对象，包含 embedding 模型、批处理大小等配置。
    collection_name : str
        要使用的 Qdrant 集合名称，由构造函数参数传入。
    vector_db : Qdrant
        Qdrant 向量存储客户端，用于添加文档嵌入。
    """

    def __init__(self, collection_name: str | None) -> None:
        """初始化嵌入管理服务。

        Parameters
        ----------
        collection_name : str or None
            Qdrant 集合名称。若为 None，则从应用配置中读取。
        """
        # 应用配置（embedding 模型、批处理大小等）
        self.cfg = config

        if collection_name:
            self.collection_name = collection_name

        # 确保集合存在后再连接
        initialize_vector_db(collection_name=self.collection_name, embeddings_size=self.cfg.embedding_size)

        # 加载 embedding 模型（LiteLLM / OpenAI 兼容接口）
        embedding = get_embedding_model(self.cfg)

        # 初始化当前集合的 Qdrant 向量存储客户端
        self.vector_db = init_vdb(collection_name=self.collection_name, embedding=embedding)

    # ------------------------------------------------------------------
    # 加载与切分
    # ------------------------------------------------------------------

    @staticmethod
    def _build_splitter() -> RecursiveCharacterTextSplitter:
        """按配置构建分块器。

        分隔符顺序即优先级：先按空行切段落，再按中文句号/问号/感叹号切句子。
        中文标点必须排在英文标点之前，否则整段中文永远切不开。
        """
        return RecursiveCharacterTextSplitter(
            chunk_size=config.chunk_size,
            chunk_overlap=config.chunk_overlap,
            length_function=len,
            separators=config.chunk_separators,
        )

    def _load_documents(self, directory: str, file_ending: str) -> list[Any]:
        """按扩展名加载目录下的文档并切分。

        ``exclude`` 排除 README：语料目录里的 README 是给人看的说明，
        进了向量库会作为一篇无关文档参与检索，拉低 Precision。

        文本文件显式按 UTF-8 读取，失败再退回 GBK：LangChain 的
        ``autodetect_encoding`` 依赖可选的 chardet，没装时会退化成 GBK 并把
        UTF-8 中文读崩，比直接指定编码更脆弱。
        """
        splitter = self._build_splitter()

        if file_ending == ".pdf":
            loader = DirectoryLoader(
                directory,
                glob="*" + file_ending,
                loader_cls=PyPDFium2Loader,
                exclude=("README.md",),
            )
            return loader.load_and_split(splitter)

        if file_ending in (".txt", ".md"):
            last_error: UnicodeDecodeError | None = None
            for encoding in ("utf-8", "gbk"):
                loader = DirectoryLoader(
                    directory,
                    glob="*" + file_ending,
                    loader_cls=TextLoader,
                    loader_kwargs={"encoding": encoding},
                    exclude=("README.md",),
                )
                try:
                    return loader.load_and_split(splitter)
                except UnicodeDecodeError as exc:
                    last_error = exc
                    logger.warning(f"{encoding} 解码失败，尝试下一种编码: {exc}")
            raise ValueError(f"无法解码目录 {directory} 下的文本文件: {last_error}")

        msg = f"File ending '{file_ending}' not supported."
        raise ValueError(msg)

    def _enrich_metadata(
        self,
        docs: list[Any],
        category: str,
        upload_time: str | None,
    ) -> None:
        """补齐元数据，供检索侧过滤与来源展示使用。

        ``source`` 统一取文件名而不是完整路径：Windows 上路径分隔符是 ``\\``，
        原来只按 ``/`` 切会让元数据里留下整条绝对路径。
        """
        chunk_index: dict[str, int] = {}
        for doc in docs:
            raw_source = doc.metadata.get("source", "unknown")
            filename = Path(raw_source).name
            doc.metadata["source"] = filename
            doc.metadata["filename"] = filename
            doc.metadata["category"] = category
            if upload_time:
                doc.metadata["upload_time"] = upload_time
            # chunk_index 按文件累计，便于回溯"原文第几段"
            doc.metadata["chunk_index"] = chunk_index.get(filename, 0)
            chunk_index[filename] = doc.metadata["chunk_index"] + 1

    # ------------------------------------------------------------------
    # Contextual Retrieval
    # ------------------------------------------------------------------

    @staticmethod
    def _create_context_llm() -> Any:
        """构造用于生成上下文前缀的 LLM（复用主对话模型，非流式）。"""
        from agent.agent.fitness_agent import _create_llm  # noqa: PLC0415 - 避免循环导入

        return _create_llm(config, streaming=False)

    def _generate_context(self, llm: Any, doc_text: str, chunk_text: str) -> str:
        """为单个 chunk 生成上下文前缀。失败时返回空串（退化为原行为）。"""
        try:
            prompt = _CONTEXT_PROMPT.format(
                doc=doc_text[:_CONTEXT_DOC_CHARS],
                chunk=chunk_text,
            )
            response = llm.invoke(prompt)
            content = getattr(response, "content", "")
            return str(content).strip().replace("\n", " ")[:120]
        except Exception as exc:  # noqa: BLE001 - 单条失败不应中断整批入库
            logger.warning(f"生成上下文前缀失败，退回原文：{exc}")
            return ""

    def _apply_contextual_retrieval(self, docs: list[Any]) -> int:
        """为每个 chunk 生成并拼接文档级上下文前缀。

        以 ``[上下文] ...`` 作为前缀拼在正文前，稠密向量和 BM25 都会索引到
        这部分文本。原始正文保留在 ``metadata["raw_text"]``，便于回滚和排查。

        Returns:
            成功生成前缀的 chunk 数。
        """
        if not docs:
            return 0

        # 按来源分组：同一篇文档的多个 chunk 共享同一份全文上下文
        by_source: dict[str, list[Any]] = {}
        for doc in docs:
            by_source.setdefault(doc.metadata.get("source", "unknown"), []).append(doc)

        llm = self._create_context_llm()
        workers = max(1, config.contextual_retrieval_max_concurrency)

        def _work(payload: tuple[str, str]) -> str:
            doc_text, chunk_text = payload
            return self._generate_context(llm, doc_text, chunk_text)

        payloads: list[tuple[str, str]] = []
        targets: list[Any] = []
        for source_docs in by_source.values():
            full_text = "\n".join(d.page_content for d in source_docs)
            for doc in source_docs:
                payloads.append((full_text, doc.page_content))
                targets.append(doc)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            contexts = list(pool.map(_work, payloads))

        generated = 0
        for doc, context in zip(targets, contexts):
            doc.metadata["raw_text"] = doc.page_content
            if context:
                doc.metadata["context"] = context
                doc.page_content = f"[上下文] {context}\n\n{doc.page_content}"
                generated += 1

        logger.info(f"Contextual Retrieval: {generated}/{len(docs)} chunks 已生成上下文前缀")
        return generated

    # ------------------------------------------------------------------
    # 入库
    # ------------------------------------------------------------------

    def embed_documents(
        self,
        directory: str,
        file_ending: str = ".pdf",
        category: str = "general",
        upload_time: str | None = None,
    ) -> int:
        """从目录加载文档，分割为文本块，生成嵌入并存入向量数据库。

        支持 PDF（.pdf）、纯文本（.txt）和 Markdown（.md）格式。

        Parameters
        ----------
        directory : str
            待嵌入文档所在的目录路径。
        file_ending : str, default ".pdf"
            文件扩展名过滤。支持的值：".pdf"、".txt"、".md"。
        category : str, default "general"
            内容分类（strength / nutrition / recovery / supplement / general），
            写入元数据后可支持按分类过滤检索。
        upload_time : str or None
            ISO 格式上传时间，写入元数据供前端展示。

        Returns
        -------
        int
            本次写入的 chunk 数。

        Raises
        ------
        ValueError
            当传入不支持的文件扩展名时抛出。
        """
        docs = self._load_documents(directory, file_ending)
        logger.info(f"Loaded {len(docs)} chunks from {file_ending} files.")

        self._enrich_metadata(docs, category=category, upload_time=upload_time)

        # 可选：为每个 chunk 生成文档级上下文前缀
        if config.contextual_retrieval_enabled:
            self._apply_contextual_retrieval(docs)

        text_list = [doc.page_content for doc in docs]
        metadata_list = [doc.metadata for doc in docs]

        # 按批次插入向量数据库（若 batch_size <= 0 则一次性全量写入）
        batch_size = self.cfg.embedding_batch_size
        if batch_size > 0:
            for i in range(0, len(text_list), batch_size):
                batch_texts = text_list[i : i + batch_size]
                batch_metadata = metadata_list[i : i + batch_size]
                self.vector_db.add_texts(texts=batch_texts, metadatas=batch_metadata)
                logger.info(f"Embedded batch {i // batch_size + 1}/{(len(text_list) + batch_size - 1) // batch_size} ({len(batch_texts)} texts)")
        else:
            self.vector_db.add_texts(texts=text_list, metadatas=metadata_list)

        logger.info("SUCCESS: Texts embedded.")
        return len(text_list)

    # ------------------------------------------------------------------
    # 便捷入口
    # ------------------------------------------------------------------

    def embed_directory_tree(
        self,
        root: str,
        category: str | None = None,
        upload_time: str | None = None,
    ) -> int:
        """递归摄入一个目录树，子目录名作为分类。

        供批量导入语料使用（``data/knowledge/strength`` → category=strength）。
        每个扩展名只加载一次，避免重复入库。

        Returns:
            摄入的 chunk 总数。
        """
        root_path = Path(root)
        if not root_path.exists():
            raise FileNotFoundError(f"目录不存在: {root}")

        total = 0
        for sub in sorted(p for p in root_path.rglob("*") if p.is_dir()):
            files = [f for f in sub.iterdir() if f.is_file()]
            extensions = sorted({f.suffix.lower() for f in files} & {".pdf", ".txt", ".md"})
            for ext in extensions:
                total += self.embed_documents(
                    directory=str(sub),
                    file_ending=ext,
                    category=category or sub.name,
                    upload_time=upload_time,
                )
        # 顶层目录下的散装文件
        extensions = sorted({f.suffix.lower() for f in root_path.iterdir() if f.is_file()} & {".pdf", ".txt", ".md"})
        for ext in extensions:
            total += self.embed_documents(
                directory=str(root_path),
                file_ending=ext,
                category=category or root_path.name,
                upload_time=upload_time,
            )
        return total


async def embed_directory_async(service: EmbeddingManagement, root: str, category: str | None = None) -> None:
    """在线程池中执行目录摄入，避免阻塞事件循环。"""
    await asyncio.to_thread(service.embed_directory_tree, root, category)
