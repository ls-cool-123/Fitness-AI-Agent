## 5.6.0 (2026-10-21)

### Feat

- **HITL**: 训练记录写库前 `interrupt()` 暂停，`POST /chat/confirm` 用 `Command(resume)` 恢复；确认状态存在 checkpointer 里，服务重启后可继续确认
- **Checkpoint**: 会话状态后端可配置（postgres / sqlite / memory），线程按 `user:conversation` 隔离，新增 `POST /chat/reset`
- **RAG**: 分块分隔符补齐中文标点；新增 Contextual Retrieval（入库前生成文档级上下文前缀）
- **Scripts**: `ingest_corpus.py` 批量导入语料、`build_corpus_eval.py` 自动生成文档级评测集、`e2e_hitl.py` 跨进程验证

### Fix

- **Documents**: 批量上传时每个文件都会把 tmp 目录里所有同后缀文件重新嵌入一遍，导致重复入库（N 个文件膨胀到 N²/2 倍 chunk）
- **Config**: `/documents/upload` 的 `category` 参数没有写入 chunk 元数据，按分类过滤检索不可用
- **VDB**: BM25 稀疏模型改为懒加载，避免 import 时触发模型下载（离线环境下 import 直接失败）
- **RAG**: NDCG 的 IDCG 改为按标注相关数计算，不再对漏召回免罚
- **Gitignore**: `lib/` 规则误伤 `frontend/src/lib`，收窄为仓库根目录

### Test

- 新增 checkpointer 跨重启恢复、HITL 中断/恢复/幂等、确认接口契约、预览次数换算等用例（单测 + 集成共 56 项）

## 5.5.0 (2025-12-05)

### Feat

- **Cohere**: Reverting to correct Cohere impl for better grounded generation

## 5.4.0 (2025-12-04)

### Feat

- **Reranking**: Adding reranking with flashrank or cohere (#133)

### Perf

- **Graph**: Performance Optimization for Graph (#134)

## 5.3.0 (2025-11-30)

### Feat

- **Graph**: Retry logik if question can not be answered (#131)

### Refactor

- **Warnings**: Supress warnings that can not be fixed
- **Frontend**: Refactor to httpx
- **Backend**: Fixing minor stuff
- **Frontend**: Refactoring the Frontend into client and assistant

## 5.2.0 (2025-11-30)

### Feat

- **Frontend**: Moving frontend to own uv project

## 5.1.0 (2025-11-30)

### Feat

- **Graph**: Defaults to gemini

## 5.0.0 (2025-11-30)

### Feat

- **Upload**: Adding upload sidebar in frontend

## 4.0.0 (2025-11-30)

### Feat

- **Langchain-1.0**: Migration to Langchain & Langgraph 1.0, fixing docker problems

### Refactor

- **Embeddings**: Removing unnessary calls and cleanup
- **Config**: Converting to Pydantic Settings and removing yml config files (#128)

## 3.2.1 (2025-11-22)

### Fix

- **LiteLLM**: Fixing deprectation warning.s

## 3.2.0 (2025-11-22)

### Feat

- **Frontend**: Reworking frontend to support streaming

## 3.1.0 (2025-11-22)

### Feat

- **Updates**: Updating Frontend and Backend

## 3.0.0 (2025-06-15)

## 2.5.0 (2023-12-26)

## 2.4.2 (2023-12-07)

## 2.4.1 (2023-11-21)

## 2.4.0 (2023-11-10)

## 2.3.0 (2023-10-13)

## 2.2.7 (2023-09-16)

## 2.2.6 (2023-09-16)

## 2.2.5 (2023-09-15)

## 2.2.4 (2023-09-13)

## 2.2.3 (2023-09-12)

## 2.2.2 (2023-09-10)

## 2.2.1 (2023-09-04)

## 2.2.0 (2023-09-04)

## 2.1.0 (2023-08-04)

## 2.0.1 (2023-07-17)

## 2.0.0 (2023-07-15)

## 1.0.2 (2023-06-06)

## 1.0.1 (2023-05-30)

## 1.0.0 (2023-05-19)
