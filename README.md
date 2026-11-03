# 🏋️ 健身 AI 助手 (Fitness AI Agent)

针对健身爱好者训练数据碎片化、知识获取低效、缺乏趋势分析三大痛点，基于 ReAct Agent 与 RAG 技术提供三大核心功能：结构化录入训练数据，上传健身文档后专业知识精准问答，历史训练数据自动生成力量趋势与训练量化分析。



---

## 目录

- [功能特性](#功能特性)
- [系统架构](#系统架构)
- [技术栈](#技术栈)
- [快速开始](#快速开始)
- [项目结构](#项目结构)
- [API 接口](#api-接口)
- [配置说明](#配置说明)
- [本地开发](#本地开发)
- [测试](#测试)
- [工具链](#工具链)

---

## 功能特性

- 🤖 **对话式 AI 教练** — 基于 LangGraph ReAct Agent，自动判断用户意图并调用对应工具
- 📚 **知识库搜索 (RAG)** — 上传健身/运动科学文档，通过语义搜索获取专业知识
- 📝 **训练记录** — 自然语言描述训练内容，自动解析并存入数据库（如 "深蹲 80kg 5组5次"）
- 📊 **进度分析** — 查询历史训练数据，追踪力量增长和训练量变化
- 🔄 **混合检索** — 稠密向量 + BM25 稀疏向量，兼顾语义理解和关键词匹配
- 🎯 **重排序 (Reranking)** — 支持 Cohere 和 FlashRank 两种重排序引擎，提升检索精度
- 🔍 **链路追踪** — 基于 Phoenix 的可观测性，监控每次 LLM 调用和检索过程
- 🌐 **REST API** — FastAPI 构建，自动生成 OpenAPI 文档
- 🖥️ **Web 前端** — React + TypeScript SPA：流式对话、工具结果富渲染、训练数据看板
- 🧠 **长期记忆** — 对话自动提取 + LLM 重要性评分，仅保留有价值信息，语义相似度 x 时间衰减精准召回
- 💾 **会话状态持久化** — LangGraph Checkpointer 支持 Postgres / SQLite / Memory 三种后端，服务重启后对话与未完成任务都可续跑，按 `user:conversation` 分线程
- ✅ **人工确认 (HITL)** — 训练记录写库前 `interrupt()` 暂停，用户确认或修正数值后 `Command(resume=...)` 从断点继续，重启不丢

---

## 系统架构

```
┌──────────────┐     ┌─────────────────────────────────────────────┐
│    React     │────►│           FastAPI 后端 (8001)                │
│   前端 (5173) │     │                                             │
└──────────────┘     │  ┌─────────────────────────────────────┐    │
                     │  │      LangGraph ReAct Agent           │    │
                     │  │  ┌─────┐ ┌─────┐ ┌─────┐ ┌──────┐  │    │
                     │  │  │聊天 │ │训练 │ │知识 │ │长期  │  │    │
                     │  │  │工具 │ │工具 │ │搜索 │ │记忆  │  │    │
                     │  │  └──┬──┘ └──┬──┘ └──┬──┘ └──┬───┘  │    │
                     │  └──────┼───────┼───────┼──────┼──────┘    │
                     │         │       │       │      │           │
                     │         │       │       │      │ fire &    │
                     │         │       │       │      │ forget    │
                     └─────────┼───────┼───────┼──────┼───────────┘
                               │       │       │      │
                      ┌────────▼──┐ ┌──▼───────▼──┐ ┌─▼──────────┐
                      │   MySQL    │ │    Qdrant    │ │  Qdrant    │
                      │  训练数据   │ │  知识库向量   │ │ 用户长期记忆 │
                      └────────────┘ └──────┬──────┘ └────────────┘
                                            │
                                     ┌──────▼──────┐
                                     │   Phoenix    │
                                     │   链路追踪    │
                                     └─────────────┘
```

### 三大核心存储

| 数据库 | 用途 | 存储内容 |
|--------|------|---------|
| **MySQL** | 结构化业务数据 | 用户档案、训练课表、动作记录、动作库 |
| **Qdrant (fitness_kb)** | 非结构化知识库 | 健身文档向量嵌入，支撑知识库 RAG 语义搜索 |
| **Qdrant (user_memories)** | 用户长期记忆 | 经 LLM 评分筛选的对话记忆，含偏好/目标/洞察 |
| **Phoenix** | 可观测性 | LLM 调用、检索步骤、Tool 使用的链路追踪 |

---

## 长期记忆系统

在原 ReAct Agent 基础上引入长期记忆层，让 AI 教练能够**跨会话记住**用户的偏好、目标和训练洞察。采用"写入前评估 + 检索时衰减"的双重筛选机制，只有真正有价值的信息才会被持久化。

### 记忆架构

```
每次对话结束 ──► fire-and-forget ──► LLM 候选提取 ──► LLM 重要性评分
                                                            │
                                              importance ≥ 0.6 的存入
                                                            │
                                                            ▼
                                                     Qdrant user_memories
                                                            │
用户新问题 ──► recall_memories_tool ──► 稠密检索 ──► BGE 精排
                                                           │
                                               rerank_score × decay
                                                           │
                                                    top_k 记忆 ──► 个性化回复
```

### 核心技术优化

**5. 长期记忆 ——** 由于原项目仅有基于 MemorySaver 的进程内短期记忆，系统重启后对话上下文全部丢失。为此引入长期记忆模块：对话后 LLM 异步提取候选记忆，以 4 维加权评分（相关性 0.35 / 特异性 0.25 / 未来有用性 0.25 / 非冗余性 0.15）做重要性评估，仅 importance ≥ 0.6 的记忆写入 Qdrant 持久化；检索时稠密召回 → BGE 精排 → 差异化指数时间衰减（半衰期 14~90 天）计算最终相关性。在 12 段模拟对话真实评测中，提取+评分管线将存储噪音率从全量对话的 47% 降至 15.4%（deepseek-v4-flash），偏好召回 Recall@5 达 63.3%，MRR 达 0.71。

### 重要性评分 —— 四维过滤

| 维度 | 权重 | 说明 |
|------|:----:|------|
| **相关性** | 0.35 | 与健身训练/健康目标的直接关联程度 |
| **特异性** | 0.25 | 含具体数据、日期、动作名称的程度（非泛泛而谈） |
| **未来有用性** | 0.25 | 未来对话中可能被引用的概率 |
| **非冗余性** | 0.15 | 与已有记忆的不重复程度 |

### 重要性阈值调优

在 12 段模拟对话（总计 32 条 ground truth 记忆项 + 24 条噪音项）上评测不同阈值的效果（模型: deepseek-v4-flash）：

| 阈值 | 记忆噪音率 ↓ | 有价值信息覆盖率 ↑ | 精确率 ↑ | F1 |
|:----:|:----------:|:--------------:|:------:|:---:|
| 0.5 | 14.8% | 71.9% | 85.2% | 0.78 |
| **0.6** | **15.4%** | **68.8%** | **84.6%** | **0.76** |
| 0.7 | 16.0% | 65.6% | 84.0% | 0.74 |

**结论:** 提取 + 评分管线把存储噪音率从全量写入的估算基线（约 47%，未单独实测）压到 15% 左右。三个模型横向对比：deepseek-v4-flash 噪音率最低（15.4%），deepseek-chat 次之（22.2%），gemini-2.5-flash 最高（27.6%）。

三档阈值在噪音率上差异很小（14.8% / 15.4% / 16.0%），主要差别在覆盖率：阈值越高，越容易把有价值但表述模糊的记忆挡在门外。因此 0.6 是**偏保守**的默认值而非"最优解"——如果更看重覆盖率，可以下调到 0.5（F1 0.78 vs 0.76）。2 段纯闲聊对话在三档阈值下均被正确识别为 0 条记忆。

### 时间衰减 —— 指数半衰模型

记忆的相关性不是一成不变的。例如，用户的健身目标在 2 个月后可能已经改变，而饮食偏好相对稳定。系统为不同记忆类型配置差异化半衰期：

```
decay = exp(-ln(2) × days_elapsed / half_life)
```

| 记忆类型 | 半衰期 | 30天后衰减 | 60天后衰减 | 设计依据 |
|----------|:------:|:---------:|:---------:|---------|
| personal_info | 90天 | 0.79 | 0.63 | 身高、体重等基本信息几乎不变 |
| user_goal | 60天 | 0.71 | 0.50 | 健身目标通常以 2-3 个月为周期调整 |
| user_preference | 45天 | 0.63 | 0.40 | 训练偏好可能随计划变化 |
| training_insight | 30天 | 0.50 | 0.25 | 训练数据持续更新，旧洞察逐渐失效 |
| conversation_summary | 14天 | 0.23 | 0.05 | 单次对话的参考价值随时间快速下降 |

### 半衰期分类优化设计

按记忆类型配置差异化半衰期（非统一 30 天）：个人信息（90天）基本不变应长期保留，训练洞察（30天）随时间失效较快，对话摘要（14天）仅作短期参考。对比统一半衰期的预期收益如下：

> 由于评测需要时间跨度至少 30-60 天才能测得真实衰减差异，当前数据为基于公式推导的理论值，后续可通过长期运行的时序数据验证。

### 去重机制

新记忆写入前与已有记忆做余弦相似度比较，阈值 0.85。超过该阈值的记忆视为重复，跳过存储。

### 检索全链路效果

预写入 20 条种子记忆（覆盖目标/偏好/伤病/训练洞察等类型），在 12 个偏好相关查询上评测端到端检索效果：

| 指标 | 值 |
|------|:---:|
| Recall@5 | 63.3% |
| Precision@5 | 28.3% |
| MRR | 0.71 |
| NDCG@5 | 0.71 |

> 12 条查询中，7 条 Recall@5 = 100%（目标、伤病、训练方式、时间偏好等宽泛查询可完美召回），3 条 Recall@5 = 0%（极窄查询如"卧推进步""鸡胸肉态度"需要更细粒度的内容匹配）。MRR 0.71 表明相关记忆平均排在首位附近。

### 记忆配置

```bash
# .env 可配置项
MEMORY_COLLECTION_NAME=user_memories   # Qdrant collection 名称
MEMORY_IMPORTANCE_THRESHOLD=0.6        # 重要性写入阈值（0.6 = 最优平衡）
MEMORY_HALF_LIFE_DAYS=30               # 默认半衰期（天）
MEMORY_MAX_PER_EXTRACTION=5            # 每次对话最多提取 5 条记忆
```

---

## 会话状态与人工确认（HITL）

原实现用 `MemorySaver` 保存对话状态，进程一重启，正在进行的对话和"等用户确认"
的操作会一起消失。现在把 checkpointer 抽成可配置后端：

| 后端 | 适用场景 | 特点 |
|------|---------|------|
| `memory` | 单测、无外部依赖的本地调试 | 重启即丢 |
| `sqlite` | 本机验证"重启续聊" | 单文件持久化，不需要额外服务 |
| `postgres` | 生产 / docker-compose | 多进程共享、崩溃恢复 |

```
CHECKPOINT_BACKEND=postgres
POSTGRES_DSN=postgresql://fitness:fitness@localhost:5433/fitness_agent
```

### 线程模型

`thread_id = "{user_id}:{conversation_id}"`。早期直接用 `user_id` 当线程 id，
在内存后端下靠"重启即清空"被动兜底；持久化之后必须按对话分线程，否则同一用户
的历史只会无限累积。`conversation_id` 缺省为 `default`，兼容未升级的前端。

| 接口 | 作用 |
|------|------|
| `POST /chat`、`POST /chat/stream` | 请求体新增可选 `conversation_id`；出现待确认操作时返回 `interrupt` |
| `POST /chat/confirm` | `{approved, edits?}` 恢复挂起的写入；无待确认任务返回 409 |
| `POST /chat/reset` | 清空当前线程的 checkpoint |

### 写入前的人工确认

```
LLM 解析动作 → add_workout_tool 内 interrupt() → 前端确认卡片
            → POST /chat/confirm → Command(resume) → 写 MySQL
```

几个实现约束：

- `interrupt()` 必须放在所有副作用之前——恢复时工具会从头重新执行；
- 工具在 Agent 图外被调用（`POST /workout/add` 表单）时**不会**触发确认，
  靠 `get_config()` 里有没有 `thread_id` 判断；
- 重复确认由"线程是否还有待恢复任务"拦住，返回 409，避免重复写库。

### 验证

```bash
# 起依赖
docker compose up -d qdrant mysql postgres
# 跨进程验证：进程 A 暂停 → 进程 B 确认 → 校验落库
uv run python scripts/e2e_hitl.py
```

> Windows 本地直连 Postgres 时，psycopg 的异步连接要求 `SelectorEventLoop`；
> 脚本里已切换事件循环策略，uvicorn 直跑则建议用 `CHECKPOINT_BACKEND=sqlite`。

---

## 技术栈

| 层级 | 技术 |
|------|------|
| **LLM 网关** | LiteLLM（统一接口，支持 DeepSeek / Gemini / Cohere / OpenAI） |
| **Agent 框架** | LangGraph（ReAct Agent + 中间件上下文管理 + 长期记忆） |
| **状态存储** | LangGraph Checkpointer（Postgres / SQLite / Memory） |
| **嵌入模型** | FastEmbed / Qwen Embedding / Google Embedding |
| **向量数据库** | Qdrant（混合检索：稠密 + BM25 稀疏向量） |
| **关系数据库** | MySQL 8.4 + SQLAlchemy + aiomysql |
| **重排序** | BGE-reranker-v2-m3 / FlashRank / Cohere Rerank |
| **链路追踪** | Arize Phoenix + OpenInference + OpenTelemetry |
| **Web 框架** | FastAPI + Uvicorn |
| **前端** | React 19 + TypeScript + Vite + Tailwind CSS + Recharts |
| **包管理** | uv（后端）/ npm（前端） |
| **容器化** | Docker Compose（含 Postgres 用于会话状态） |

---

## 快速开始

### 前置条件

- [Docker](https://docs.docker.com/get-docker/) & Docker Compose
- （可选）[uv](https://docs.astral.sh/uv/getting-started/installation/) 用于本地开发

### 1. 克隆项目

```bash
git clone https://github.com/mfmezger/conversational-agent-langchain.git
cd conversational-agent-langchain
```

### 2. 配置环境变量

复制模板文件并填入 API Key：

```bash
cp template.env .env
```

**必须配置的 Key：**

| 变量 | 说明 |
|------|------|
| `GEMINI_API_KEY` | Google Gemini API 密钥 |
| `COHERE_API_KEY` | Cohere API 密钥（重排序） |
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥（对话模型，推荐） |
| `QWEN_API_KEY` | 阿里云 DashScope API 密钥（嵌入模型） |

### 3. 启动服务

```bash
docker compose up -d
```

### 4. 访问服务

| 服务 | URL |
|------|-----|
| **API 文档** | http://127.0.0.1:8001/docs |
| **聊天前端** | http://localhost:5173 |
| **Qdrant 控制台** | http://localhost:6333/dashboard |
| **Phoenix 追踪** | http://localhost:6006 |

---

## 项目结构

```
项目2/
├── src/agent/
│   ├── main.py                  # FastAPI 应用入口 + 生命周期管理
│   ├── agent/
│   │   ├── fitness_agent.py     # LangGraph ReAct Agent 构建
│   │   └── checkpointing.py     # 会话状态后端（memory/sqlite/postgres）
│   ├── api/                     # REST API 路由
│   │   ├── chat.py              # POST /chat — 对话接口
│   │   ├── workout.py           # POST /workout/add, GET /workout/history
│   │   └── documents.py         # POST /documents/upload — 文档上传
│   ├── tools/                   # Agent 可调用的工具
│   │   ├── add_workout.py       # 记录训练
│   │   ├── query_workout.py     # 查询训练历史
│   │   ├── analyze_progress.py  # 分析训练进展
│   │   ├── rag_search.py        # 搜索健身知识库
│   │   └── recall_memories.py   # 召回用户长期记忆
│   ├── db/                      # MySQL 相关
│   │   ├── models.py            # SQLAlchemy ORM 模型
│   │   └── mysql.py             # 异步引擎和会话管理
│   ├── rag/                     # RAG 管线
│   │   ├── ingest.py            # 文档摄入
│   │   └── retriever.py         # 检索 + 重排序
│   ├── parser/
│   │   └── workout_parser.py    # 自然语言训练文本解析
│   ├── memory/                   # 长期记忆系统
│   │   ├── __init__.py           # 模块入口 + 异步提取主流程
│   │   ├── models.py             # 记忆数据模型（Candidate/Scored/Payload）
│   │   ├── store.py              # Qdrant 记忆存储（写入/检索/去重）
│   │   ├── retriever.py          # 记忆检索（粗筛 → 重排 → 时间衰减）
│   │   └── extractor.py          # LLM 记忆提取 + 4 维重要性评分
│   ├── utils/
│   │   ├── vdb.py               # Qdrant 向量数据库连接
│   │   ├── config.py            # Pydantic 配置管理
│   │   ├── retriever.py         # 检索器工厂函数
│   │   └── reranker.py          # 重排序器
│   └── routes/                  # 旧版 API 路由（向后兼容）
│       ├── collection.py
│       ├── embeddings.py
│       ├── search.py
│       ├── rag.py
│       └── delete.py
├── frontend/                     # React SPA
│   ├── index.html
│   ├── package.json
│   ├── vite.config.ts            # 开发代理：/chat /workout /documents → :8001
│   ├── nginx.conf                # 生产反向代理（proxy_buffering off）
│   └── src/
│       ├── main.tsx  App.tsx  index.css
│       ├── lib/                  # api / NDJSON 流式读取 / 配色 / 工具函数
│       ├── types/tools.ts        # 工具输出的联合类型 + 类型守卫
│       └── components/
│           ├── ui/               # 基础组件
│           ├── chat/             # 对话面板 + 工具结果卡片
│           ├── workout/          # 快速记录训练
│           ├── documents/        # 知识库上传
│           └── dashboard/        # 训练数据看板（Recharts）
├── tests/                       # 测试
├── docker-compose.yml           # 服务编排
├── Dockerfile                   # 后端镜像
├── Dockerfile.frontend          # 前端镜像
├── Makefile                     # 开发命令快捷方式
├── pyproject.toml               # 项目依赖和配置
└── template.env                 # 环境变量模板
```

---

## API 接口

### 对话

```
POST /chat            — 非流式问答（可能返回 interrupt）
POST /chat/stream     — NDJSON 流式问答（含 interrupt 事件）
POST /chat/confirm    — 确认/取消待写入的训练记录
POST /chat/reset      — 清空当前对话线程
```

向 AI 教练发送消息，Agent 自动判断意图并调用对应工具。

```json
{
  "user_id": "uuid",
  "messages": [
    {"role": "user", "content": "今天深蹲80kg 5组5次，卧推60kg 3组8次"}
  ],
  "collection_name": "fitness_kb"
}
```

### 训练记录

```
POST /workout/add              — 自然语言记录训练
GET  /workout/history          — 查询训练历史
GET  /workout/progress         — 进展分析 + 按日期的重量/训练量序列（看板用）
GET  /workout/category-summary — 各身体部位的训练量汇总（看板用）
```

### 知识库

```
POST /documents/upload — 上传健身文档（PDF/TXT/MD）
```

### 旧版接口（向后兼容）

```
POST /embeddings/embed_documents   — 嵌入文档
POST /semantic/semantic_search     — 语义搜索
POST /rag/qa                       — 基于文档的问答
DELETE /embeddings/delete          — 删除嵌入
```

---

## 配置说明

主要通过 `.env` 文件配置，由 [config.py](src/agent/utils/config.py) 中的 Pydantic Settings 加载：

### 模型配置

```bash
# 对话模型
DEEPSEEK_API_KEY=sk-xxx         # DeepSeek API 密钥
DEEPSEEK_MODEL_NAME=deepseek-chat
GEMINI_API_KEY=xxx              # Google Gemini（需通过 LiteLLM 使用）

# 嵌入模型
EMBEDDING_PROVIDER=qwen         # google / qwen / openai / dashscope
EMBEDDING_MODEL_NAME=text-embedding-v4
EMBEDDING_SIZE=768
```

### 重排序配置

```bash
RERANK_PROVIDER=bge              # bge（本地）/ siliconflow（远程免费）/ flashrank / none
RERANK_TOP_K=5                   # 重排序后保留的文档数
RERANK_CANDIDATES=15             # 送进 Cross-Encoder 的候选数（见下方延迟说明）
BGE_RERANKER_PATH=               # 本地模型目录（离线环境）
RERANK_API_BASE=https://api.siliconflow.cn/v1
RERANK_API_KEY=                  # provider=siliconflow 时必填
```

**为什么候选数从 40 降到 15**：BGE-reranker-v2-m3 在 CPU 上重排 40 条约 33 秒，
用户每问一次知识库就要等半分钟。粗筛的覆盖率曲线（`scripts/recall_at_k.py`）：

| 候选数 | 理论上限 Recall | 本地 BGE 实测延迟 |
|:---:|:---:|:---:|
| 40 | 1.0000 | ~33 s |
| 20 | 0.9667 | ~17 s |
| **15** | **0.9583** | **~8–15 s** |
| 10 | 0.9417 | ~8 s |

15 条只损失 4 个点的理论上限，延迟降到 1/2～1/4；再往下损失变大。对延迟更敏感
可以切 `RERANK_PROVIDER=siliconflow`，把重排挪到远端（免费，毫秒级返回）。

### 检索配置

```bash
RETRIEVAL_K=40                    # 初始检索文档数
RETRIEVAL_K_RETRY=100             # 重试时的检索数
```

### 文档分块与 Contextual Retrieval

```bash
CHUNK_SIZE=750                    # 分块长度（字符）
CHUNK_OVERLAP=200                 # 相邻块重叠
# 分隔符默认已包含中文标点（。！？；，），否则中文会被按字符硬切
CONTEXTUAL_RETRIEVAL_ENABLED=false  # 入库前为每个 chunk 生成文档级上下文前缀
```

### 会话状态与 HITL

```bash
CHECKPOINT_BACKEND=memory         # memory / sqlite / postgres
POSTGRES_DSN=postgresql://fitness:fitness@localhost:5433/fitness_agent
SQLITE_CHECKPOINT_PATH=data/checkpoints.sqlite
CHECKPOINT_TTL_DAYS=30
WORKOUT_CONFIRM_ENABLED=true      # 训练记录写入前是否 interrupt 等确认
```

> 首次在本地跑检索前需要 BM25 模型，离线环境请设置
> `FASTEMBED_CACHE_PATH=./fastembed_cache`（docker-compose 已挂载到容器内）。

### 离线 / 内网环境

HF 缓存如果是 Linux 容器里下载的，快照目录在 Windows 上会变成无法解析的符号链接，
表现为"模型明明在本地却连不上 HuggingFace"。两个环境变量可以完全绕过下载：

```bash
BM25_MODEL_PATH=resources/bm25_model      # 含 english.txt 的目录即可
BGE_RERANKER_PATH=resources/bge_reranker  # CrossEncoder 直接加载本地目录
```

`resources/bge_reranker` 可用脚本从已有缓存"落地"成普通文件（同盘硬链接，不占额外空间）：

```bash
uv run python scripts/materialize_hf_model.py \
    --repo BAAI/bge-reranker-v2-m3 --cache hf_cache/hub --out resources/bge_reranker
```

### 数据库配置

```bash
# MySQL
DATABASE_URL=mysql+aiomysql://root:root@localhost:3306/fitness_agent

# Qdrant
QDRANT_URL=http://localhost
QDRANT_API_KEY=test
QDRANT_PORT=6333

# Phoenix
PHOENIX_COLLECTOR_ENDPOINT=http://phoenix:4318/v1/traces
```

---

## 本地开发

### 安装依赖

```bash
uv sync                    # 后端
cd frontend && npm ci      # 前端
```

### 单独启动 Qdrant

本地开发时不需要启动全部 Docker 服务，只需 Qdrant 和 MySQL：

```bash
docker compose up -d qdrant mysql
```

### 启动后端

```bash
uv run uvicorn src.agent.main:app --reload --port 8001
```

### 启动前端

```bash
cd frontend && npm run dev
```

Vite dev server 监听 5173，并把 `/chat`、`/workout`、`/documents` 代理到后端
8001，因此浏览器始终同源请求，后端不需要 CORS 配置。后端不在默认端口时用
`BACKEND_URL` 覆盖：

```bash
BACKEND_URL=http://localhost:9001 npm run dev
```

### Makefile 快捷命令

| 命令 | 说明 |
|------|------|
| `make setup` | 安装依赖和 git hooks |
| `make style` | 运行代码格式化/检查 |
| `make test` | 运行单元测试和集成测试 |
| `make start_backend` | 启动 FastAPI 后端 |
| `make start_frontend` | 启动 React 开发服务器（Vite） |
| `make start_docker` | 启动全部 Docker 服务 |
| `make restart` | 重建并重启所有服务 |
| `make clean` | 清理构建产物 |

---

## 测试

```bash
# 单元测试和集成测试（并行执行）
uv run pytest -n auto -m "not vcr and not e2e" -v tests/

# VCR 录制测试
uv run pytest -m "vcr" -v tests/

# E2E 测试（需要完整服务运行）
RUN_LIVE_E2E=1 uv run pytest -m "e2e" -v tests/

# 覆盖率报告
uv run coverage run -m pytest tests/ && uv run coverage html

# 前端测试（NDJSON 流式解析的分块边界用例）
cd frontend && npm test
```

### 测试标记

| 标记 | 说明 |
|------|------|
| `unit` | 纯单元测试 |
| `integration` | 集成测试（进程内依赖） |
| `contract` | 接口契约测试 |
| `e2e` | 端到端测试（需要外部服务） |
| `vcr` | 基于 HTTP 录播的测试 |
| `slow` | 耗时较长的测试 |

---

## 工具链

| 工具 | 用途 |
|------|------|
| [ruff](https://github.com/astral-sh/ruff) | 代码格式化和 linting |
| [prek](https://prek.j178.dev/) | Rust 原生 git hooks |
| [commitizen](https://commitizen-tools.github.io/commitizen/) | 规范化 commit 信息 |
| [mypy](https://www.mypy-lang.org/) | 静态类型检查 |
| [pytest](https://pytest.org/) | 测试框架 |
| [Bruno](https://www.usebruno.com/) | API 测试客户端 |

---

## 什么是 RAG？

检索增强生成（Retrieval-Augmented Generation）是一种增强大语言模型（LLM）的技术。它不依赖模型预训练时记住的知识，而是**实时从外部知识库检索相关文档**，将这些文档作为上下文提供给 LLM，从而：

- 减少幻觉（hallucination）
- 回答私有/专业领域数据的问题
- 保证信息时效性

本项目中，用户上传的健身文档被分段、嵌入后存入 Qdrant。提问时，系统先检索最相关的段落，再交给 LLM 合成回答。

### 混合检索

本系统同时使用两种检索方式：

1. **稠密向量检索** — 基于语义理解，找到"意思相近"的内容
2. **稀疏向量检索 (BM25)** — 基于关键词匹配，确保精确命中

两者结果融合，兼顾语义广度和关键词精度。

---

## Star History

<a href="https://star-history.com/#mfmezger/conversational-agent-langchain&Date">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=mfmezger/conversational-agent-langchain&type=Date&theme=dark" />
    <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=mfmezger/conversational-agent-langchain&type=Date" />
    <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=mfmezger/conversational-agent-langchain&type=Date" />
  </picture>
</a>
