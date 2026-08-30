# 多智能体模块方案

## 现状分析

当前架构是**单一 ReAct Agent**（[fitness_agent.py](../src/agent/agent/fitness_agent.py)），一个 LLM + 3 个工具，所有推理都在一个 Agent 内完成。

```
用户 → /chat API → FitnessAgent (ReAct) → [query_workout / analyze_progress / rag_search]
```

**问题**：
- 所有逻辑耦合在一个 prompt 里，越来越长时 LLM 容易"走神"
- 无法并行处理（比如同时查训练数据 + 查知识库）
- 专业领域（营养 vs 训练 vs 康复）混在一起，难以独立优化

**优势**（已有的好基础）：
- 已用 LangGraph（原生支持多 Agent 图编排）
- 工具已模块化（`tools/` 目录下各自独立）
- FastAPI + 流式输出基建完善

---

## 推荐架构：Supervisor + Specialist 模式

这是 LangGraph 多 Agent 最成熟的模式，也是当前项目改动最小、收益最大的方案：

```
                         ┌─────────────────┐
                         │  Supervisor Agent │  ← 路由器，理解意图后分发
                         └──────┬──────────┘
                                │
              ┌─────────────────┼─────────────────┐
              ▼                 ▼                  ▼
    ┌─────────────┐   ┌──────────────┐   ┌──────────────┐
    │ Workout Agent│   │ Knowledge Agent│  │ Analysis Agent│
    │ (训练记录)    │   │ (知识检索)     │   │ (数据分析)     │
    └─────────────┘   └──────────────┘   └──────────────┘
```

### 各 Agent 职责

| Agent | 职责 | 工具 |
|---|---|---|
| **Supervisor** | 理解意图，路由到合适的 Specialist；汇总结果返回用户 | 无（纯路由） |
| **WorkoutAgent** | 查询/记录训练数据 | `query_workout_tool`, `add_workout_tool` |
| **KnowledgeAgent** | 搜索健身知识库 | `rag_search_tool` |
| **AnalysisAgent** | 分析训练趋势、生成报告 | `analyze_progress_tool` |

### 为什么选这个模式

1. **工具互不重叠** —— 当前 3 个工具的职责边界天然清晰，拆分后每个 Specialist 只关心自己的工具
2. **Supervisor 逻辑简单** —— 就是一个分类器（查训练？查知识？分析？），不需要复杂推理
3. **可独立优化** —— 比如 KnowledgeAgent 可以用更好的 RAG prompt，不影响训练查询
4. **并行友好** —— 用户问"我最近卧推有进步吗？帮我查查怎么改善"，可以同时调 WorkoutAgent + KnowledgeAgent

---

## 实现路径（3 个阶段）

### Phase 1：抽取 Specialist Agent（改动最小）

在 `src/agent/agent/` 下新建 `specialists/` 目录，每个 Specialist 是一个独立的 `create_agent()` 实例：

```
src/agent/agent/
├── fitness_agent.py        # 现有文件，后续变为 Supervisor
├── specialists/
│   ├── __init__.py
│   ├── workout_agent.py    # 训练记录 Specialist
│   ├── knowledge_agent.py  # 知识检索 Specialist
│   └── analysis_agent.py   # 数据分析 Specialist
```

每个 Specialist 的结构与当前 `build_fitness_agent()` 相同（`create_agent(model, tools=[...], system_prompt=...)`），只是 tool 列表缩小、prompt 更聚焦。

**关键代码示例**（`workout_agent.py`）：
```python
from langchain.agents import create_agent
from agent.tools import query_workout_tool, add_workout_tool

WORKOUT_PROMPT = """你是训练记录管理助手。你负责帮助用户查询和记录训练。
- 查询历史用 query_workout_tool
- 记录训练用 add_workout_tool
用中文回复，简洁明了。"""

def build_workout_agent(llm):
    return create_agent(
        model=llm,
        tools=[query_workout_tool, add_workout_tool],
        system_prompt=WORKOUT_PROMPT,
    )
```

### Phase 2：实现 Supervisor 路由

Supervisor 本身也是一个 Agent，但不调用业务工具 —— 它只做一件事：看用户消息 → 决定派给哪个 Specialist。

LangGraph 提供了内置的 `create_supervisor()` 函数（LangGraph ≥1.1.3 已支持）：

```python
from langgraph.prebuilt import create_supervisor

# Phase 1 构建的各个 Specialist
workout_agent = build_workout_agent(llm)
knowledge_agent = build_knowledge_agent(llm)
analysis_agent = build_analysis_agent(llm)

# Supervisor 自动管理路由和状态
supervisor = create_supervisor(
    agents=[workout_agent, knowledge_agent, analysis_agent],
    model=llm,
    prompt=(
        "你是健身教练主管。根据用户意图将请求分发给合适的专家：\n"
        "- WorkoutAgent: 训练记录查询/添加\n"
        "- KnowledgeAgent: 健身知识/动作要领/营养\n"
        "- AnalysisAgent: 数据分析/进展报告\n"
        "如果用户同时需要多种信息，可以依次调用多个专家。"
    ),
).compile(checkpointer=memory)
```

### Phase 3：API 层适配 & 流式优化

- `/chat` 和 `/chat/stream` 的调用入口从 `fitness_agent.ainvoke()` 改为 `supervisor.ainvoke()`
- 流式事件中新增 `supervisor_decision` 类型的事件，前端可显示"正在为您分配专家..."
- `config` 传递保持不变（`thread_id` = user_id）

---

## 目录结构变更

```
src/agent/
├── agent/
│   ├── fitness_agent.py          # 改为 build_supervisor() + 兼容导出
│   ├── specialists/
│   │   ├── __init__.py
│   │   ├── workout_agent.py
│   │   ├── knowledge_agent.py
│   │   └── analysis_agent.py
│   └── prompts.py                # 从 backend/prompts.py 迁入，按 Agent 拆分
├── api/
│   └── chat.py                   # 少量改动：import supervisor 替代 fitness_agent
├── backend/
│   └── prompts.py                # 保留兼容导入
├── tools/                        # 不变
└── ...
```

---

## 不推荐的方向

- **Swarm/多 Agent 辩论**：健身场景不需要多个 Agent 对同一问题给出意见然后投票，这是做复杂推理/代码审查才用的
- **完全去中心化**：没有 Supervisor 的 peer-to-peer Agent 网 —— 调试困难，状态管理复杂，对当前规模来说过重
- **每用户一个 Agent 实例**：当前 MemorySaver 已通过 `thread_id` 隔离用户，不需要创建更多实例

---

## 风险 & 注意事项

1. **延迟增加**：多 Agent 意味着多轮 LLM 调用（Supervisor 一次 + 每个 Specialist 一次），对用户感知延迟有约 2-3 倍的影响
   - **缓解**：Supervisor 用更便宜的模型（如 DeepSeek-V3 做路由，V3-Pro 做 Specialist 推理）
2. **MemorySaver 内存膨胀**：当前是进程内内存，多 Agent 的状态更大
   - **缓解**：后续可切换为 SqliteSaver 持久化
3. **兼容性**：`create_supervisor` 是 LangGraph 较新 API，需要确认当前 `langgraph>=1.1.3` 已包含
