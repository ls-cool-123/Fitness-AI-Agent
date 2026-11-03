import pytest
from unittest.mock import MagicMock, patch
from agent.utils.vdb import initialize_vector_db, generate_collection, init_vdb, initialize_all_vector_dbs
from agent.utils.config import Config

@patch("agent.utils.vdb.load_vec_db_conn")
def test_initialize_vector_db_exists(mock_load_conn):
    mock_client = MagicMock()
    mock_client.collection_exists.return_value = True
    mock_load_conn.return_value = mock_client

    initialize_vector_db("test_coll", 1536)

    mock_client.collection_exists.assert_called_with(collection_name="test_coll")
    # Should NOT call create_collection
    mock_client.create_collection.assert_not_called()

@patch("agent.utils.vdb.load_vec_db_conn")
def test_initialize_vector_db_not_exists(mock_load_conn):
    mock_client = MagicMock()
    mock_client.collection_exists.return_value = False
    mock_load_conn.return_value = mock_client

    initialize_vector_db("test_coll", 1536)

    mock_client.collection_exists.assert_called_with(collection_name="test_coll")
    mock_client.create_collection.assert_called_once()

    # 不再调用 set_sparse_model：那会让 qdrant_client 自己下一份 fastembed 模型，
    # 离线环境建集合都会失败。稀疏向量由客户端计算，服务端只要 IDF 修饰符。
    mock_client.set_sparse_model.assert_not_called()
    kwargs = mock_client.create_collection.call_args.kwargs
    assert "fast-sparse-bm25" in kwargs["sparse_vectors_config"]

@patch("agent.utils.vdb.QdrantVectorStore")
@patch("agent.utils.vdb.FastEmbedSparse")
def test_init_vdb(mock_sparse, mock_vstore):
    mock_embedding = MagicMock()

    init_vdb("test_coll", mock_embedding)

    mock_vstore.assert_called_once()
    args, kwargs = mock_vstore.call_args
    assert kwargs["collection_name"] == "test_coll"
    assert kwargs["embedding"] == mock_embedding

@patch("agent.utils.vdb.initialize_vector_db")
def test_initialize_all_vector_dbs(mock_init_vdb):
    config = Config()
    initialize_all_vector_dbs(config)

    # 主集合 + 健身知识库 + 用户记忆三个集合都要初始化
    assert mock_init_vdb.call_count == 3
    assert [c.kwargs["collection_name"] for c in mock_init_vdb.call_args_list] == [
        config.qdrant_collection_name,
        config.fitness_collection_name,
        config.memory_collection_name,
    ]
