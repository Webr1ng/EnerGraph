"""docs/plan_memory_module.md — EnerGraph 记忆模块开发计划

本文为开发计划文档（Markdown），非 Python 模块。文件头遵循 CLAUDE.md 约定。
所属层：docs
依赖：docs/research_memory_frameworks.md（选型依据）
对接算法层：N/A（记忆属 Agent 层基础设施，非计算引擎）
"""

# EnerGraph 记忆模块开发计划

> **配套文档**：[research_memory_frameworks.md](research_memory_frameworks.md)（选型调研报告）
> **创建日期**：2026-06-24
> **作者**：魏博源
> **分支**：`feature/memory-system`

---

## 1. 选型结论

**主方案：LangGraph 原生记忆（checkpoint + store）+ LangMem 长期语义层**
**备选：Mem0 OSS（触发条件见调研报告 §5）**
**放弃：Zep/Graphiti（强依赖 Neo4j，过重）**

### 选型理由（数据支撑，非凭感觉）

| 决策因子 | 结论 | 数据来源 |
|----------|------|----------|
| 原生契合 LangGraph 1.2 | LangMem 是 LangChain 官方记忆层，同源最低摩擦 | 调研报告 §2.1 |
| 零新增重型依赖 | L1/L2 共用一个 Postgres（PostgresSaver + PostgresStore） | 调研报告 §2.3 |
| 全本地/数据不出网 | 自有 Postgres，不依赖外部 SaaS；Mem0 唯一稳定 MCP 是云端（数据出网） | 调研报告 §1.4 |
| 中文召回可控 | embedder 复用现有 bge-small-zh；规避 Mem0 BM25/实体硬编码英文（#4884/#5549） | 调研报告 §1.6 |
| 不违反 MCP 优先 | 记忆是 Agent 层基础设施，非算法计算引擎，走 LangGraph Tool 合规 | 调研报告 §0 |

---

## 2. 架构设计

### 2.1 三层记忆划分

```
┌─ L3 知识检索 ──────────────────────────────────────────┐
│  ChromaDB HVAC RAG（5605 条）— 保持不变，独立           │
│  → query_hvac_knowledge 工具（已实现）                   │
└────────────────────────────────────────────────────────┘
┌─ L2 长期记忆 ──────────────────────────────────────────┐
│  LangGraph store + LangMem（PostgresStore）             │
│  → 跨会话语义记忆：用户偏好 / 站点事实 / 决策历史         │
│  → search_memory / save_memory 工具（新增）              │
│  → 按 namespace 隔离（agent_id 维度）                    │
└────────────────────────────────────────────────────────┘
┌─ L1 短期记忆 ──────────────────────────────────────────┐
│  LangGraph checkpoint（PostgresSaver）                  │
│  → 线程级对话历史 + AgentState 快照                      │
│  → thread_id 维度（单次会话上下文窗口）                  │
└────────────────────────────────────────────────────────┘
        ↑ L1 与 L2 共用同一个 PostgreSQL 实例（不同表）
```

### 2.2 在 EnerGraph 架构中的位置

| 现有组件 | 与记忆模块的关系 |
|----------|------------------|
| `AgentState`（state.py） | 新增 `thread_id` 字段驱动 checkpoint；L2 记忆不污染 State（按需检索注入 system message） |
| `cognitive_parser` 节点 | **入口注入**：检索 L2 记忆 → 拼入 system prompt（"用户历史偏好"段） |
| 新增 `memory_manager` 节点 | **出口写入**：会话结束/有新事实时，调 LangMem 写入 L2 store |
| `TOOL_REGISTRY`（tools） | 注册 `search_memory` / `save_memory` 两个记忆工具（Pydantic I/O） |
| 各 Agent 子图（HVAC/PowerAI/UI Router） | 按 `agent_id` namespace 隔离各自的长期记忆空间 |
| ChromaDB（L3） | 保持不变，与 L2 记忆概念分离（知识 vs 记忆） |

### 2.3 多智能体记忆隔离方案

每个 Agent 子图通过 **namespace 前缀**隔离长期记忆：

```
namespace 格式：[agent_id, scope, entity_id]

示例：
  ["powerai", "user_preference", "user_001"]     # PowerAI 用户偏好
  ["powerai", "site", "FJJB000001"]               # PowerAI 站点事实
  ["hvac_expert", "session", "thread_abc"]        # HVAC 会话记忆
  ["ui_router", "user_preference", "user_001"]    # UI Router 用户偏好
```

- 短期记忆（L1 checkpoint）天然按 `thread_id` 隔离，无需额外处理。
- 长期记忆（L2 store）通过 namespace 前缀 `agent_id` 实现跨 Agent 隔离。
- 跨 Agent 记忆复用（如 PowerAI 想读 HVAC 的设备偏好）通过显式 namespace 跨域读取，**默认不互通**。

---

## 3. 分阶段开发任务（Task 粒度，每个可独立 commit）

> 所有 Task 遵循 CLAUDE.md：文件头 docstring、绝对导入、Pydantic I/O、try-except 错误处理、Tool 必须测试。

### Task 1: LangGraph PostgresSaver 持久化接入（L1 短期记忆）

**目标**：替换当前无持久化/InMemory 状态，启用 LangGraph checkpoint 线程级持久化。

**改动**：
- `requirements.txt`：新增 `langgraph-checkpoint-postgres`、`psycopg[binary,pool]`
- `config/agent_config.yaml` + `settings.py`：新增 `MemoryConfig`（postgres_dsn、enabled 开关）
- `src/graph/builder.py`：编译图时注入 `checkpointer=PostgresSaver(...)`，支持开关回退 InMemorySaver（本地开发/测试）
- `.env.example`：新增 `MEMORY_POSTGRES_DSN`、`MEMORY_ENABLED`

**验收**：相同 `thread_id` 二次 invoke 能恢复上下文；`MEMORY_ENABLED=false` 时回退 InMemory 不报错。

**commit**：`[graph] 接入 LangGraph PostgresSaver 线程级 checkpoint`

### Task 2: Docker Compose 部署配置（Postgres + pgvector）

**目标**：一键起本地 Postgres（含 pgvector，为 L2 向量索引预留）。

**改动**：
- 新增 `docker-compose.yml`（项目根）：`postgres` 服务（pgvector/pgvector 镜像）+ 卷持久化 + 健康检查
- 新增 `.env.example`：`POSTGRES_USER/PASSWORD/DB/PORT`
- README 简述启动方式（`docker compose up -d`）

**验收**：`docker compose up -d` 后 Postgres 可连；`MEMORY_POSTGRES_DSN` 指向它。

**commit**：`[config] 新增记忆模块 Postgres+pgvector Docker Compose`

### Task 3: 记忆工具封装（L2 长期记忆 Tool）

**目标**：封装 `search_memory` / `save_memory` 两个工具，注册到 `TOOL_REGISTRY`，符合 Pydantic I/O 规范。

**改动**：
- `src/schemas/memory.py`：`MemoryQuery` / `MemoryItem` / `MemorySearchResult`（Pydantic BaseModel）
- `src/memory/store.py`：封装 LangMem/LangGraph store 客户端（单例），含 `agent_id` namespace 注入；try-except 异常返回 `{"error": "memory: ..."}`
- `src/tools/memory_ops.py`：`search_memory(query, agent_id, namespace)` / `save_memory(content, agent_id, namespace)`
- `src/tools/__init__.py`：注册到 `TOOL_REGISTRY` + `TOOL_SCHEMAS`

**验收**：两工具单元测试通过（正常/边界/非法输入）；store 不可用时返回 error dict 不崩 Agent。

**commit**：`[tools] 新增记忆工具 search_memory/save_memory（L2 长期记忆）`

### Task 4: Graph 节点集成（memory_manager 节点 + Prompt）

**目标**：在图编排中接入记忆检索（入口）与写入（出口）。

**改动**：
- `src/graph/nodes.py`：新增 `memory_manager_node`（出口写入）；`cognitive_parser_node` 入口增加 L2 记忆检索注入 system prompt
- `src/graph/builder.py`：接入 memory_manager 节点（位于 interpreter_generator 之后或会话结束处）
- `src/config/prompts/main_graph.yaml`：新增 `memory_injection_hint`（"用户历史偏好"段注入规则）、`memory_extraction_hint`（哪些事实值得写入 L2）—— **Prompt 单独 commit**
- **注意**：Prompt 必须从 `settings.prompts` 引用 key，节点代码不得硬编码 prompt 字符串

**验收**：连续两轮会话第二轮能引用第一轮记忆；prompt 文件单独 commit。

**commit 1（代码）**：`[graph] 新增 memory_manager 节点，cognitive_parser 注入 L2 记忆`
**commit 2（Prompt）**：`[config] main_graph 新增 memory_injection/extraction_hint Prompt`

### Task 5: 多智能体记忆隔离（agent_id 维度）

**目标**：HVAC/PowerAI/UI Router 各自独立记忆空间，默认不互通。

**改动**：
- `src/graph/agents/base_agent.py`：`BaseAgent` 新增 `memory_namespace` 属性（默认 `[self.name]`）
- 各 Agent 子图（`hvac_expert/`、`powerai/`、`ui_router/`）的 agent_id 传入记忆工具
- `src/memory/store.py`：namespace 解析逻辑（按 `agent_id` 路由到不同 store key 前缀）

**验收**：HVAC 写入的记忆不被 PowerAI 默认检索到；显式跨域读取可工作。

**commit**：`[graph] 多智能体记忆按 agent_id namespace 隔离`

### Task 6: 测试用例（遵循现有测试规范）

**目标**：覆盖正常/边界/非法输入，纯计算/Mock，不依赖 LLM/API Key。

**改动**：
- `src/tests/test_memory_store.py`：store 封装单测（namespace 隔离、异常返回 error dict）
- `src/tests/test_memory_tools.py`：`search_memory`/`save_memory` 工具测试（正常/边界/非法输入）
- `src/tests/test_memory_isolation.py`：多智能体记忆隔离测试

**验收**：`pytest src/tests/test_memory*.py -v` 全通过；全量 `pytest src/tests/` 无回归。

**commit**：`[test] 记忆模块单测：store/工具/多智能体隔离`

---

## 4. 依赖变更（requirements.txt）

| 包 | 用途 | Task |
|----|------|------|
| `langgraph-checkpoint-postgres` | LangGraph PostgresSaver（L1 checkpoint） | 1 |
| `psycopg[binary,pool]` | Postgres 异步驱动（Saver/Store 共用） | 1 |
| `langmem` | LangMem 长期记忆工具（L2 store 之上） | 3 |

> ⚠️ `langmem` 与 `langgraph` 1.2 的版本兼容矩阵需在 Task 1/3 核实（调研报告 §2.5 数据缺口）。`chromadb` 已有，L3 不变。

---

## 5. 配置变更（.env.example）

新增环境变量（均带默认值，本地开发可不配则记忆禁用回退）：

```ini
# ─── 记忆模块 ───
MEMORY_ENABLED=false                    # 是否启用持久化记忆（false 回退 InMemory/无记忆）
MEMORY_POSTGRES_DSN=postgresql://energraph:energraph@localhost:5432/energraph
# LangGraph checkpoint（L1）
CHECKPOINT_TABLE=checkpoints            # PostgresSaver 表名
# LangGraph store + LangMem（L2）
STORE_TABLE=store                       # PostgresStore 表名
MEMORY_NAMESPACE_PREFIX=energraph       # 全局 namespace 前缀
```

---

## 6. 与原"四件套"规划的对比

> 原 AI_CONTEXT §1.3 规划：`Redis 工作记忆 + Milvus 短期记忆 → Neo4j 长期记忆 + ES 反思记忆`

| 能力 | 原四件套 | 新方案 | 说明 |
|------|----------|--------|------|
| 工作记忆（线程级） | Redis | LangGraph checkpoint（PostgresSaver） | ✅ 保留，复用 Postgres |
| 短期记忆（会话级） | Milvus | LangGraph checkpoint 的 thread 窗口 | ✅ 保留（合并进 checkpoint） |
| 长期记忆（语义事实） | Neo4j | LangGraph store + LangMem（PostgresStore） | ✅ 保留，去 Neo4j 重型依赖 |
| 反思记忆（经验提炼） | Elasticsearch | **暂缓**（未来可加 LangMem 的 reflection 或 Mem0） | ⚠️ 放弃初期建设，标记为未来演进 |
| 闭环学习 / Event Sourcing | Neo4j + ES | **暂缓**（对齐 V3.0 第 4 层未来演进） | ⚠️ 超出当前阶段 |

**保留的核心能力**：工作记忆 + 短期记忆 + 长期语义记忆（三层全覆盖）。
**放弃的能力（本期）**：反思记忆（ES）、闭环学习/经验提炼、知识图谱多跳推理（Neo4j）。
**放弃的理由**：当前阶段优先"轻量化、可落地、低运维"，避免引入 Redis/Milvus/Neo4j/ES 四个独立中间件。反思与闭环学习对齐 V3.0 第 4 层（自演化引擎层）的未来演进，按 AI_CONTEXT §1.3 中长期路线单独推进。

---

## 7. 风险与缓解

| 风险 | 缓解 |
|------|------|
| LangMem 与 LangGraph 1.2 版本不兼容 | Task 1 先做版本兼容验证；不兼容则降级为纯 LangGraph store（去 LangMem） |
| LangMem 文档偏少 / 胶水代码多 | 集中封装到 `src/memory/store.py`，对外暴露简洁 Tool 接口 |
| 记忆写入引入额外 LLM 开销 | save_memory 做成显式工具调用（非每轮自动），由 memory_manager 节点按需触发 |
| Postgres 单点 | 本期接受单点；未来可加只读副本/连接池（psycopg pool 已预留） |
| 中文记忆召回 | embedder 复用 bge-small-zh；store 向量索引用 pgvector |

---

## 8. 执行顺序与里程碑

```
Task 1（PostgresSaver） → Task 2（Docker Compose）   可并行
        ↓
Task 3（记忆工具）         依赖 Task 1/2 的 Postgres
        ↓
Task 4（Graph 节点 + Prompt）  依赖 Task 3
        ↓
Task 5（多智能体隔离）         依赖 Task 3/4
        ↓
Task 6（测试）                贯穿，每个 Task 同步补测
```

**里程碑**：Task 1+2 完成 = L1 持久化可用；Task 3+4 完成 = L2 长期记忆闭环；Task 5+6 完成 = 多智能体记忆隔离 + 质量保障。
