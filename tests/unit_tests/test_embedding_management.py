import pytest
from unittest.mock import MagicMock, patch
from agent.backend.services.embedding_management import EmbeddingManagement
from langchain_core.documents import Document

@pytest.fixture
def mock_config():
    with patch("agent.backend.services.embedding_management.config") as mock_cfg:
        mock_cfg.embedding_provider = "google"
        mock_cfg.embedding_model_name = "embed-english-v3.0"
        mock_cfg.embedding_size = 1024
        mock_cfg.embedding_batch_size = 0
        # 分块参数必须给出具体值：_build_splitter 会读取它们
        mock_cfg.chunk_size = 750
        mock_cfg.chunk_overlap = 200
        mock_cfg.chunk_separators = ["\n\n", "\n", "。"]
        mock_cfg.contextual_retrieval_enabled = False
        mock_cfg.contextual_retrieval_max_concurrency = 2
        yield mock_cfg

@pytest.fixture
def mock_init_vdb():
    with patch("agent.backend.services.embedding_management.init_vdb") as mock_vdb:
        yield mock_vdb

@pytest.fixture
def mock_initialize_vector_db():
    # 集合初始化会真的连 Qdrant；单测里必须屏蔽，否则没起服务就跑不了
    with patch(
        "agent.backend.services.embedding_management.initialize_vector_db"
    ) as mock_init:
        yield mock_init

@pytest.fixture
def mock_get_embedding_model():
    with patch("agent.backend.services.embedding_management.get_embedding_model") as mock_embed:
        mock_embed.return_value = MagicMock()
        yield mock_embed

@pytest.fixture
def embedding_service(
    mock_config, mock_init_vdb, mock_initialize_vector_db, mock_get_embedding_model
):
    return EmbeddingManagement(collection_name="test_collection")

def test_init_success(mock_config, mock_init_vdb, mock_initialize_vector_db, mock_get_embedding_model):
    service = EmbeddingManagement(collection_name="test_collection")

    assert service.collection_name == "test_collection"
    mock_get_embedding_model.assert_called_once_with(mock_config)
    mock_init_vdb.assert_called_once()
    mock_initialize_vector_db.assert_called_once_with(
        collection_name="test_collection", embeddings_size=1024
    )

def test_init_invalid_provider(mock_config, mock_initialize_vector_db):
    mock_config.embedding_provider = "unknown_provider"

    with pytest.raises(KeyError, match="No suitable embedding Model configured!"):
        EmbeddingManagement(collection_name="test_collection")

@patch("agent.backend.services.embedding_management.DirectoryLoader")
@patch("agent.backend.services.embedding_management.RecursiveCharacterTextSplitter")
def test_embed_documents_pdf(mock_splitter_cls, mock_loader_cls, embedding_service):
    # Setup mocks
    mock_loader = MagicMock()
    mock_loader_cls.return_value = mock_loader

    mock_doc = Document(page_content="test content", metadata={"source": "/path/to/test.pdf"})
    mock_loader.load_and_split.return_value = [mock_doc]

    # Call method
    embedding_service.embed_documents(directory="tests/resources/", file_ending=".pdf")

    # Assertions
    mock_loader_cls.assert_called_once()
    mock_loader.load_and_split.assert_called_once()
    embedding_service.vector_db.add_texts.assert_called_once()

    # Verify metadata processing (source path cleanup)
    call_args = embedding_service.vector_db.add_texts.call_args
    assert call_args is not None
    metadatas = call_args.kwargs.get("metadatas") or call_args[1] # handle both keyword and positional args if needed, though code uses kwargs
    assert metadatas[0]["source"] == "test.pdf"

@patch("agent.backend.services.embedding_management.DirectoryLoader")
@patch("agent.backend.services.embedding_management.RecursiveCharacterTextSplitter")
def test_embed_documents_txt(mock_splitter_cls, mock_loader_cls, embedding_service):
    # Setup mocks
    mock_loader = MagicMock()
    mock_loader_cls.return_value = mock_loader
    mock_loader.load_and_split.return_value = []

    # Call method
    embedding_service.embed_documents(directory="tests/resources/", file_ending=".txt")

    # Assertions
    mock_loader_cls.assert_called_once()

def test_embed_documents_invalid_extension(embedding_service):
    with pytest.raises(ValueError, match="not supported"):
        embedding_service.embed_documents(directory="tests/resources/", file_ending=".docx")

def test_default_separators_cover_chinese_punctuation() -> None:
    """配置里的默认分隔符必须覆盖中文标点，且排在英文标点之前。

    这是修复"中文被按字符硬切"的核心：分隔符按顺序尝试，英文句点排在中文
    句号之前时，中文段落根本没有可切分的标记。
    """
    from agent.utils.config import Config

    separators = Config().chunk_separators
    for mark in ("。", "！", "？"):
        assert mark in separators
    assert separators.index("。") < separators.index(".")


def test_build_splitter_passes_config_through(embedding_service, mock_config):
    """分块器必须使用配置里的 chunk_size / overlap / separators。"""
    with patch(
        "agent.backend.services.embedding_management.RecursiveCharacterTextSplitter"
    ) as splitter_cls:
        embedding_service._build_splitter()

    kwargs = splitter_cls.call_args.kwargs
    assert kwargs["chunk_size"] == mock_config.chunk_size
    assert kwargs["chunk_overlap"] == mock_config.chunk_overlap
    assert kwargs["separators"] == mock_config.chunk_separators


@patch("agent.backend.services.embedding_management.DirectoryLoader")
def test_contextual_retrieval_prepends_prefix(
    mock_loader_cls, embedding_service, mock_config
):
    """开启后每个 chunk 前要拼上文档级上下文，原文保留在 raw_text。"""
    from langchain_core.documents import Document

    mock_config.contextual_retrieval_enabled = True
    mock_loader = MagicMock()
    mock_loader_cls.return_value = mock_loader
    mock_loader.load_and_split.return_value = [
        Document(page_content="深蹲时膝盖不要内扣。", metadata={"source": "/p/squat.md"}),
        Document(page_content="下蹲至大腿平行地面。", metadata={"source": "/p/squat.md"}),
    ]

    fake_llm = MagicMock()
    fake_llm.invoke.return_value = MagicMock(content="深蹲动作要领")
    with patch.object(embedding_service, "_create_context_llm", return_value=fake_llm):
        count = embedding_service.embed_documents(
            directory="fake", file_ending=".md", category="strength"
        )

    assert count == 2
    call = embedding_service.vector_db.add_texts.call_args
    texts = call.kwargs["texts"]
    metadatas = call.kwargs["metadatas"]

    assert all(text.startswith("[上下文] 深蹲动作要领") for text in texts)
    assert metadatas[0]["raw_text"] == "深蹲时膝盖不要内扣。"
    assert metadatas[0]["category"] == "strength"
    assert metadatas[0]["chunk_index"] == 0
    assert metadatas[1]["chunk_index"] == 1
