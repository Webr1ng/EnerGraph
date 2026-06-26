"""docs/plan_memory_module.md — EnerGraph 记忆模块开发计划

本文为开发计划文档（Markdown），非 Python 模块。文件头遵循 CLAUDE.md 约定。
所属层：docs
依赖：docs/research_memory_frameworks.md（选型依据）
对接算法层：N/A（记忆属 Agent 层基础设施，非计算引擎）
"""

# EnerGraph 记忆模块开发计划

> **配套文档**：[research_memory_frameworks.md](research_memory_frameworks.md)（选型调研报告）
> **创建日期**：2026-06-24
> **作者**：周溥林、魏博源
> **分支**：`feature/memory-system`

---

## 1. 选型结论

**主方案：LangGraph 原生记忆（checkpoint + store）+ LangMem 长期语义层**
**备选：Mem0 OSS（触发条件见调研报告 §5）**
**放弃：Zep/Graphiti（图数据库体系对本期过重）**

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

### 2.3 多智能体记忆隔离与共享方案

**原则**：物理共享一套记忆基础设施，逻辑上按智能体隔离，少量全局记忆显式共享。

EnerGraph 不采用“一个智能体一个数据库”，也不采用“所有智能体共用一锅记忆”。L1 checkpoint 与 L2 store 仍共用同一个 PostgreSQL / LangGraph Store；L2 长期记忆通过 namespace 维度隔离：

```text
同一个 PostgreSQL / LangGraph Store
  ├─ env
  ├─ site_id
  ├─ agent_id
  └─ memory_type
```

每个 Agent 子图通过 **namespace 前缀**隔离长期记忆：

```
namespace 格式：[global_prefix, env, tenant_or_site, agent_id, scope, entity_id]

示例：
  ["energraph", "prod", "FJJB000001", "powerai", "user_preference", "user_001"]
  ["energraph", "prod", "FJJB000001", "powerai", "site", "FJJB000001"]
  ["energraph", "dev", "local", "hvac_expert", "session", "thread_abc"]
  ["energraph", "prod", "FJJB000001", "ui_router", "user_preference", "user_001"]
```

- 短期记忆（L1 checkpoint）天然按 `thread_id` 隔离，无需额外处理。
- 长期记忆（L2 store）通过 `global_prefix + env + tenant_or_site + agent_id` 实现环境、租户/站点、Agent 多级隔离。
- 默认每个 Agent 拥有自己的长期记忆 namespace，例如：

```text
prod / jiangbei_factory / powerai
prod / jiangbei_factory / hvac_expert
prod / jiangbei_factory / ui_router
prod / jiangbei_factory / carbon_mgmt
```

- PowerAI 的调度经验不得默认污染 HVAC 专家问答；UI Router 的页面操作偏好不得被误当成储能调度约束。
- 跨 Agent 记忆复用必须通过显式 namespace 跨域读取，**默认不互通**。

#### 2.3.1 显式共享记忆 namespace

为站点稳定事实和通用偏好预留 `global` / `site` 共享 namespace：

```text
prod / jiangbei_factory / global
```

适合写入共享 namespace 的内容：

- 站点稳定事实：厂区名称、设备配置、建筑结构
- 用户通用偏好：报告先给结论、用中文、偏好表格
- 企业级安全红线：SOC 不低于 20%、禁止越过某些运行边界
- 已确认的长期业务约束

这些记忆可被多个 Agent 读取，但写入必须满足“稳定、长期、跨业务有效”的条件。

#### 2.3.2 默认不共享的记忆

以下记忆默认只服务当前 Agent，不跨 Agent 注入：

- `device_state`：当前设备状态、告警、瞬时功率，必须设置 TTL，过期不得使用
- `decision_history`：某个 Agent 的历史决策，只能作为该 Agent 的上下文
- 调度策略细节：PowerAI 的储能策略不应自动进入 HVAC 专家判断
- 页面操作上下文：UI Router 的导航历史不应污染业务判断

#### 2.3.3 推荐读写顺序

每个 Agent 检索记忆时可以读两层：

```text
1. global/site 共享记忆
2. 当前 agent_id 专属记忆
```

写入时默认写入当前 Agent 专属 namespace；只有明确属于站点事实、安全约束、用户长期偏好时，才写入共享 namespace。

一句话结论：**底层共库，namespace 隔离；默认私有，显式共享；安全约束和站点事实共享，临时状态和决策历史隔离。**

### 2.4 记忆数据模型与时效性

L2 记忆不是普通文本缓存，必须保留最小元数据，避免把过期设备状态或临时策略当成永久事实。

| 字段 | 说明 |
|------|------|
| `content` | 记忆正文，面向 LLM 注入的简洁事实描述 |
| `memory_type` | `user_preference` / `site_fact` / `decision_history` / `device_state` / `safety_constraint` 等 |
| `source_thread_id` | 来源会话，用于审计和回溯 |
| `site_id` | 站点 ID；没有站点上下文时填 `local` 或 `unknown` |
| `agent_id` | 写入该记忆的 Agent |
| `confidence` | 0-1 置信度，LLM 提取或规则写入时给出 |
| `created_at` / `updated_at` | 创建与更新时间 |
| `valid_until` / `ttl_seconds` | 可选；临时状态、告警、策略建议必须有时效 |
| `tags` | 可选标签，如 `["powerai", "dispatch", "peak-valley"]` |

**时效性规则**：
- 用户偏好、站点基础事实可长期保存，但仍允许显式更新/删除。
- 设备运行状态、告警、单次调度建议必须设置 `valid_until` 或 `ttl_seconds`。
- 决策历史默认保留摘要，不保存完整长报告；完整执行链路交给 checkpoint / 日志系统。
- 检索注入时优先过滤过期记忆，再按相似度、memory_type、confidence 组合排序。

### 2.5 写入策略：同步检索，延迟/按需提取

- **入口检索同步执行**：`cognitive_parser` 进入前根据 query + namespace 检索 L2，命中结果注入 system prompt。
- **出口写入不每轮强制执行**：`memory_manager` 只在满足提取规则时写入，如用户明确偏好、站点事实变化、重要决策被确认。
- **优先合并上下文后提取**：参考 LangMem background/debounce 思路，会话活动稳定后再提炼，避免用户连续追问时重复消耗 LLM。
- **失败不阻断主流程**：写入失败只记录 error，不影响用户获得本轮调度/问答结果。

---

## 3. 分阶段开发任务（Task 粒度，每个可独立 commit）

> 所有 Task 遵循 CLAUDE.md：文件头 docstring、绝对导入、Pydantic I/O、try-except 错误处理、Tool 必须测试。

### Task 1: LangGraph PostgresSaver 持久化接入（L1 短期记忆）

**目标**：替换当前无持久化/InMemory 状态，启用 LangGraph checkpoint 线程级持久化。

**改动**：
- `requirements.txt`：新增 `langgraph-checkpoint-postgres`、`psycopg[binary,pool]`
- `config/agent_config.yaml` + `settings.py`：新增 `MemoryConfig`（postgres_dsn、enabled 开关）
- `src/graph/builder.py`：编译图时注入 `checkpointer=PostgresSaver(...)`，支持开关回退 InMemorySaver（本地开发/测试）
- `src/graph/builder.py` 或 `src/memory/store.py`：首次启用 Postgres checkpointer 时显式调用 `.setup()` 建表；手动传入 psycopg 连接时确保 `autocommit=True`、`row_factory=dict_row`
- 安全配置：设置 `LANGGRAPH_STRICT_MSGPACK=true` 或显式传入安全反序列化白名单，避免 checkpoint 反序列化风险
- `.env.example`：新增 `MEMORY_POSTGRES_DSN`、`MEMORY_ENABLED`

**验收**：相同 `thread_id` 二次 invoke 能恢复上下文；首次启动自动/显式完成 checkpoint 表初始化；`MEMORY_ENABLED=false` 时回退 InMemory 不报错。

**commit**：`[graph] 接入 LangGraph PostgresSaver 线程级 checkpoint`

### Task 2: PostgreSQL 部署配置（已调整为外部提供）

**目标**：生产/联调环境可连接 PostgreSQL（含 pgvector，为 L2 向量索引预留）。

> 2026-06-26 调整：仓库不再内置 `docker-compose.yml`。本地人工联调优先使用 `MEMORY_DEMO_FILE_STORE_ENABLED=true` 的 demo 文件落盘；需要验证生产级 Postgres checkpoint/store 时，由运维或开发者自行提供 PostgreSQL + pgvector，并通过 `MEMORY_POSTGRES_DSN` 指向该实例。

**改动**：
- README / 记忆实现说明记录外部 PostgreSQL 与 demo 文件落盘两条路径

**验收**：外部 PostgreSQL 可连；`MEMORY_POSTGRES_DSN` 指向它。本地 demo 文件落盘无需 PostgreSQL。

**commit**：`[config] 记忆模块 PostgreSQL 外部部署说明`

### Task 3: 记忆工具封装（L2 长期记忆 Tool）

**目标**：封装 `search_memory` / `save_memory` 两个工具，注册到 `TOOL_REGISTRY`，符合 Pydantic I/O 规范。

**改动**：
- `src/schemas/memory.py`：`MemoryQuery` / `MemoryItem` / `MemorySearchResult`（Pydantic BaseModel）
- `src/schemas/memory.py`：补充 `memory_type`、`site_id`、`source_thread_id`、`confidence`、`valid_until`、`ttl_seconds`、`tags` 等元数据字段
- `src/memory/store.py`：封装 LangMem/LangGraph store 客户端（单例），含 `global_prefix/env/site_id/agent_id` namespace 注入；try-except 异常返回 `{"error": "memory: ..."}`
- `src/tools/memory_ops.py`：`search_memory(query, agent_id, site_id, namespace)` / `save_memory(content, agent_id, site_id, metadata)`
- `src/tools/__init__.py`：注册到 `TOOL_REGISTRY` + `TOOL_SCHEMAS`

**验收**：两工具单元测试通过（正常/边界/非法输入）；store 不可用时返回 error dict 不崩 Agent；过期记忆默认不返回；namespace 中 dev/prod、site、agent 均能隔离。

**commit**：`[tools] 新增记忆工具 search_memory/save_memory（L2 长期记忆）`

### Task 4: Graph 节点集成（memory_manager 节点 + Prompt）

**目标**：在图编排中接入记忆检索（入口）与写入（出口）。

**改动**：
- `src/graph/nodes.py`：新增 `memory_manager_node`（出口写入/延迟提取入口）；`cognitive_parser_node` 入口增加 L2 记忆检索注入 system prompt
- `src/graph/builder.py`：接入 memory_manager 节点（位于 interpreter_generator 之后或会话结束处）
- `src/config/prompts/main_graph.yaml`：新增 `memory_injection_hint`（"用户历史偏好"段注入规则）、`memory_extraction_hint`（哪些事实值得写入 L2）—— **Prompt 单独 commit**
- **注意**：Prompt 必须从 `settings.prompts` 引用 key，节点代码不得硬编码 prompt 字符串

**验收**：连续两轮会话第二轮能引用第一轮记忆；临时设备状态过期后不再注入；未命中记忆时不影响主流程；prompt 文件单独 commit。

**commit 1（代码）**：`[graph] 新增 memory_manager 节点，cognitive_parser 注入 L2 记忆`
**commit 2（Prompt）**：`[config] main_graph 新增 memory_injection/extraction_hint Prompt`

### Task 5: 多智能体记忆隔离（agent_id 维度）

**目标**：HVAC/PowerAI/UI Router 各自独立记忆空间，默认不互通。

**改动**：
- `src/graph/agents/base_agent.py`：`BaseAgent` 新增 `memory_namespace` 属性（默认 `[settings.memory.namespace_prefix, settings.env, site_id, self.name]`）
- 各 Agent 子图（`hvac_expert/`、`powerai/`、`ui_router/`）的 agent_id 传入记忆工具
- `src/memory/store.py`：namespace 解析逻辑（按 `env/site_id/agent_id` 路由到不同 store key 前缀）

**验收**：dev/prod 互不污染；不同 site 互不污染；HVAC 写入的记忆不被 PowerAI 默认检索到；显式跨域读取可工作。

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
LANGGRAPH_STRICT_MSGPACK=true           # checkpoint 反序列化安全开关
# LangGraph checkpoint（L1）
CHECKPOINT_TABLE=checkpoints            # PostgresSaver 表名
# LangGraph store + LangMem（L2）
STORE_TABLE=store                       # PostgresStore 表名
MEMORY_NAMESPACE_PREFIX=energraph       # 全局 namespace 前缀
MEMORY_ENV=dev                          # dev / staging / prod，用于 namespace 隔离
MEMORY_DEFAULT_TTL_SECONDS=0            # 0 表示长期有效；临时状态由 Tool/节点显式指定 ttl
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
| 记忆写入引入额外 LLM 开销 | save_memory 做成显式工具调用（非每轮自动），由 memory_manager 节点按需触发；后续可用 background/debounce 批处理 |
| 临时状态被误当长期事实 | `memory_type` + `valid_until/ttl_seconds` 强制区分，检索时过滤过期记忆 |
| 多环境/多站点记忆串库 | namespace 固定包含 `global_prefix/env/site_id/agent_id`，测试覆盖 dev/prod、site、agent 隔离 |
| Postgres 单点 | 本期接受单点；未来可加只读副本/连接池（psycopg pool 已预留） |
| 中文记忆召回 | embedder 复用 bge-small-zh；store 向量索引用 pgvector |

---

## 8. 执行顺序与里程碑

```
Task 1（PostgresSaver） → Task 2（外部 PostgreSQL 配置）   可并行
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
