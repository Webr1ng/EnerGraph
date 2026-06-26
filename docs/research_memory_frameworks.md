"""docs/research_memory_frameworks.md — LLM Agent 记忆框架选型调研报告

本文为调研文档（Markdown），非 Python 模块。文件头遵循 CLAUDE.md 约定。
所属层：docs
依赖：无
对接算法层：N/A
"""

# 记忆框架选型调研报告（Mem0 / LangMem / Zep / Graphiti）

> **用途**：为 EnerGraph（LangGraph 1.2 + MCP 优先 + 已有 ChromaDB + 企业级本地部署 + 中文能源领域）的记忆模块选型提供数据支撑。
> **调研日期**：2026-06-24
> **补充核实**：2026-06-25（补齐 LangMem / Graphiti 关键版本与部署事实；Mem0 版本滚动更新）
> **作者**：魏博源
> **数据来源声明**：
> - **Mem0**：完整一手核实（PyPI / GitHub / docs.mem0.ai）。✅
> - **LangMem**：已补齐 PyPI / GitHub / 官方文档关键事实。✅
> - **Graphiti**：已补齐 GitHub README 中的后端依赖事实。✅
> - **Zep CE**：License / 开源版定位仍需企业商用前单独核实。⚠️

---

## 0. EnerGraph 的选型约束（决策锚点）

| 约束 | 来源 | 含义 |
|------|------|------|
| LangGraph 1.2 | AI_CONTEXT §2.1 | 记忆方案应原生适配 LangGraph 的 checkpoint / store 抽象 |
| MCP 优先 | CLAUDE.md 架构红线 §2 | **仅约束"算法模型层计算引擎"**，记忆属 Agent 层基础设施，不强求 MCP |
| 企业级 + 数据不出网 | 项目性质 | **禁止依赖把记忆发往外部云的 SaaS** |
| 已有 ChromaDB（HVAC RAG） | AI_CONTEXT §2.1 | 5605 条语料，知识检索层保持不变 |
| 已规划 PostgresSaver | AI_CONTEXT §1.3 近期规划 | Postgres 已在引入路径上，应让记忆层复用同一 Postgres |
| 中文能源领域 | 业务 | 记忆检索的中文召回质量是硬指标 |
| 不引入图数据库重型依赖 | 选型偏好 | 本期排除 Neo4j/FalkorDB/Neptune 等图数据库体系 |

> **关键澄清**：CLAUDE.md 的 "MCP 优先" 红线针对的是**算法模型层的计算引擎**（预测/诊断/优化模型）。记忆是 Agent 层的持久化基础设施，走 LangGraph 原生 store 或 Tool 即可，**不违反 MCP 优先原则**。这一点对后续 Code Review 至关重要。

---

## 1. Mem0（mem0ai/mem0）— 完整核实 ✅

### 1.1 版本与活跃度

| 指标 | 值 | 来源 |
|---|---|---|
| PyPI `mem0ai` 最新版本 | **2.0.8** | [pypi.org/project/mem0ai](https://pypi.org/project/mem0ai/)（2026-06-25 复核） |
| 2.0.8 发布时间 | **2026-06-24** | 同上 |
| GitHub release tag | **v2.0.7**（2026-06-17，PyPI 已滚动至 2.0.8） | [github.com/mem0ai/mem0/releases](https://github.com/mem0ai/mem0/releases)（2026-06-25） |
| Stars | **~59.4k** | [github.com/mem0ai/mem0](https://github.com/mem0ai/mem0)（2026-06-25） |
| 最近 push | **2026-06-24（当天）** | 同上 |
| License | **Apache-2.0** | GitHub API + README 末尾交叉确认 |
| Python 要求 | `>=3.10, <4.0` | PyPI `requires_python` |

**结论**：极度活跃，当日仍有合并提交；Apache-2.0 商用友好。2026 年内经历 1.x→2.0→"v3 算法"多次大改，**生产环境应 pin 版本**。

### 1.2 核心架构（提取 / 去重 / 遗忘 / Graph）

来源：README "New Memory Algorithm (April 2026)" 段 + [docs.mem0.ai/llms.txt](https://docs.mem0.ai/llms.txt)。

- **提取**：2026-04 起的新算法（v3）改为 **ADD-only**（"one LLM call, no UPDATE/DELETE. Memories accumulate; nothing is overwritten"），放弃旧的"提取→冲突→UPDATE/DELETE"模型，改为只追加。
- **多信号检索**：语义 + BM25 关键词 + 实体匹配，三路并行打分融合。
- **实体链接**：抽取实体→嵌入→跨记忆链接（**基于嵌入，非独立图数据库**）。
- **时序推理**：对"当前/过去/未来"事件排序。
- **去重/遗忘**：新版写入阶段不再自动 UPDATE/DELETE；未发现显式"记忆衰减/遗忘（decay/forgetting）"机制（仍提供 `update_memory`/`delete_memory` 供显式调用）。
- **Graph Memory**：OSS 的图存储能力已被弱化/移除（当前仓库 `mem0/graphs/` 目录不存在，OSS 配置文档 grep "graph" 零命中），完整多跳 Graph Memory 现为 **Platform（托管）专属功能**。

### 1.3 与 LangGraph 集成

来源：[docs.mem0.ai/integrations/langgraph](https://docs.mem0.ai/integrations/langgraph)（已取 `.md` 原文）。

- **集成方式 = 工具式**：在 Graph 节点内手动调用 Mem0 客户端（`mem0.search(...)` → 拼进 system message → LLM 生成 → `mem0.add(...)`）。**不是** LangGraph 原生 `BaseStore`/checkpoint 适配器。
- 短期对话上下文仍靠 LangGraph 自带 checkpoint（`thread_id` + `add_messages`）；Mem0 负责**跨会话长期记忆**。
- 自托管把 `MemoryClient` 换成 `from mem0 import Memory`（OSS 库类）即可。
- 安装：`pip install langgraph langchain-openai mem0ai`。

### 1.4 MCP Server（本项目最关注）

**官方提供 MCP Server，但分两条路径，且状态分化严重**（来源：[docs.mem0.ai/platform/mem0-mcp](https://docs.mem0.ai/platform/mem0-mcp) + llms.txt）：

| 路径 | 端点/形态 | 状态 | 对 EnerGraph 的契合 |
|------|----------|------|---------------------|
| **(a) 云端托管 MCP（主推）** | `https://mcp.mem0.ai/mcp`（http），暴露 11 个工具 | ✅ 稳定 | ❌ **记忆数据发往 mem0 云，与企业本地/数据不出网冲突** |
| **(b) 自托管 MCP（OpenMemory）** | 仓库 `openmemory/`，Docker 镜像 `mem0/openmemory-mcp`，对接自有 Qdrant+LLM | ⚠️ **Sunset 中** | ⚠️ README 顶部明确 Sunset Notice；独立仓库 `mem0ai/mem0-mcp` **已于 2026-03-24 归档** |

**结论**：Mem0 唯一稳定的官方 MCP 是云端（数据出网）；唯一全本地的 MCP（OpenMemory）正在被废弃。若坚持"全本地 + MCP"，需用 OSS `Memory` 库 + 自有 Chroma + 本地 LLM 作后端，**自己用 MCP Server SDK 包一层**，而不要依赖将被废弃的官方本地 MCP。

### 1.5 生产部署（Docker / 向量库 / 本地化）

| 形态 | 命令 | 组件 |
|------|------|------|
| 库（Library） | `pip install mem0ai`（混合检索加 `[nlp]`） | 仅进程内，无服务器 |
| 自托管服务器（推荐本地路径） | `cd server && make bootstrap` / `docker compose up -d`（:3000） | FastAPI REST + 仪表盘 + 鉴权；默认 **pgvector** |
| 云平台 | 注册 app.mem0.ai | 托管，零运维 |

**支持的向量库（OSS，极全）**：Qdrant（默认）、**Chroma**、**pgvector**、Milvus、Pinecone、Redis、Elasticsearch、FAISS 等（llms.txt 第 466-493 行逐一列出）。**Chroma 与 pgvector 均为一等支持** —— EnerGraph 现有 ChromaDB 可直接复用。

**完全本地化**：✅ 支持。OSS 库 + 自托管服务器全程不连 mem0 云；LLM 可换 Ollama/vLLM，embedder 可换 HuggingFace 本地模型（默认 OpenAI，需替换）。

### 1.6 已知坑与局限（对 EnerGraph 最相关）

| 坑 | 证据 | 影响 |
|----|------|------|
| **BM25/实体抽取硬编码英文** | [#4884](https://github.com/mem0ai/mem0/issues/4884)、[#5549](https://github.com/mem0ai/mem0/issues/5549)（均 open，未合并） | **中文能源领域召回质量实质受损**，需自配中文分词或暂关混合检索 |
| 官方 MCP 向云端收敛 | `mem0-mcp` 仓库 2026-03-24 归档；OpenMemory sunset | 纯本地 MCP 路径目前最不稳定，是选型最大风险点 |
| 版本迭代破坏性强 | 多份迁移指南（oss-v2-to-v3 等） | 必须 pin 版本，否则生产事故 |
| Graph Memory 在 OSS 被弱化 | OSS 无 `mem0/graphs/` 目录 | 多跳图谱能力需上 Platform（云） |
| 每次记忆写入走 LLM | README benchmark p50 ~0.88–1.09s | 成本/延迟随规模上升 |

### 1.7 Mem0 初步判断

成熟、极度活跃、Apache-2.0、向量库生态极广（含 Chroma/pgvector）。**但对"LangGraph + MCP 优先 + 企业级本地 + 中文能源领域"的组合，契合度是"可用但有明确代价"**：官方稳定 MCP 是云端（与企业本地冲突），唯一全本地 MCP 正在 sunset，且 OSS 的 BM25/实体抽取硬编码英文会拖累中文召回。最稳妥落地：OSS `Memory` 库 + 自有 Chroma + 本地 LLM 后端 + 自包 MCP 层，pin 版本，自配中文检索。

---

## 2. LangMem（langchain-ai/langmem）— 已补齐关键核实 ✅

> **数据状态**：2026-06-25 已补齐 PyPI / GitHub / 官方文档关键事实；仍需在开发 Task 1/3 中做项目内实际安装与兼容性验证。

### 2.0 版本与活跃度

| 指标 | 值 | 来源 |
|---|---|---|
| PyPI `langmem` 最新版本 | **0.0.30** | [pypi.org/project/langmem](https://pypi.org/project/langmem/)（2026-06-25） |
| 0.0.30 发布时间 | **2025-10-27** | 同上 |
| Stars | **~1.5k** | [github.com/langchain-ai/langmem](https://github.com/langchain-ai/langmem)（2026-06-25） |
| License | **MIT** | PyPI / GitHub |
| Python 要求 | `>=3.10` | PyPI |

### 2.1 定位

LangMem 是 **LangChain 官方**的长期记忆库，专为 LangGraph 的记忆需求设计。官方文档明确说明：LangMem 提供记忆提取、Prompt 优化、长期记忆管理能力，并且原生集成 LangGraph 的长期记忆 Store。核心思想：**短期记忆走 LangGraph checkpoint（线程级对话历史），长期记忆走 LangGraph `store`（跨线程语义记忆）**，LangMem 在 `store` 之上提供记忆管理/检索工具。

### 2.2 核心架构（与 LangGraph 的关系）

- 构建在 LangGraph 的 **`store`（`BaseStore` / `InMemoryStore` / `AsyncPostgresStore` / `PostgresStore`）** 抽象之上。
- 提供工厂函数生成工具：`create_manage_memory_tool(namespace=...)`（写入/更新记忆）、`create_search_memory_tool(namespace=...)`（检索记忆）。
- 用 **namespace** 组织记忆空间（天然支持按 `agent_id` / `user_id` / `site_id` 隔离）。
- 记忆提取/更新用 LLM（语义记忆）。
- 与 checkpoint 是**两套独立机制**：checkpoint 管线程内状态（short-term），store 管跨线程事实（long-term）。
- 官方文档还提供 `ReflectionExecutor` / background memory processing 思路，可将记忆提取延后到会话活动稳定后执行，避免每条消息都触发 LLM 提取。

### 2.3 能否与 PostgresSaver 共用同一 Postgres（重点）

- ✅ **架构上可以**：LangGraph 的 `PostgresStore` / `AsyncPostgresStore`（长期记忆）与 `PostgresSaver` / `AsyncPostgresSaver`（checkpoint）连接同一个 Postgres 实例，管理**不同的表**（checkpoint 用 checkpoint 相关表，store 用 store 相关表）。
- 这意味着 EnerGraph 只需**引入一个 Postgres**，同时承载线程级 checkpoint + 跨会话语义记忆 —— **零额外重型依赖**，且 Postgres 本就在 AI_CONTEXT 近期规划中。
- ⚠️ **落地注意**：`langgraph-checkpoint-postgres` 官方文档要求首次使用 `PostgresSaver` / `AsyncPostgresSaver` 时调用 `.setup()` 创建表；手动传入 psycopg 连接时需注意 `autocommit=True`、`row_factory=dict_row` 等参数。store 的向量索引建议使用 pgvector，具体 `AsyncPostgresStore` 初始化参数留到 Task 1/3 做项目内验证。

### 2.4 MCP 支持

- LangMem **无官方 MCP Server**。记忆通过 LangGraph Tool（注册到 `TOOL_REGISTRY`）或节点内直接调用 store 访问 —— 符合 CLAUDE.md（记忆非计算引擎，不强求 MCP）。

### 2.5 成熟度与局限

| 维度 | 评估 |
|------|------|
| 与 LangGraph 集成 | ✅ **最原生**（官方同源） |
| 社区规模 | 小于 Mem0（约 1.5k stars），但与 LangGraph 官方生态强绑定 |
| 文档完整度 | 已有 memory tools / background processing / namespace 示例，但仍需项目内胶水封装 |
| 版本绑定 | 与 LangGraph 版本紧密（EnerGraph 用 1.2，需在 Task 1/3 实装验证） |
| 中文支持 | ✅ 取决于 embedder（EnerGraph 已用 bge-small-zh，可控） |

### 2.6 LangMem 初步判断

对"已用 LangGraph 1.2 + 想最小化新增组件 + 数据不出网"场景，LangMem + LangGraph 原生 store 是**架构上最契合**的选择 —— 它就是 LangGraph 的记忆层。代价是生态小于 Mem0、需补胶水代码，版本兼容需在 Task 1/3 实测。工程实现上建议采用"入口同步检索 + 出口延迟/按需写入"：检索不额外消耗 LLM，写入尽量由 `memory_manager` 合并上下文后提取，避免每轮对话都做昂贵的长期记忆提炼。

---

## 3. Zep / Graphiti — Graphiti 已补齐后端事实，Zep CE 待核实 ⚠️

> **数据状态**：Graphiti 后端依赖已于 2026-06-25 复核；Zep CE 的当前 License / 开源版定位仍需未来评估时单独核实。

### 3.1 Graphiti（getzep/graphiti）

- **时序知识图谱引擎**（temporal knowledge graph）：节点+带时间戳的边，支持"时间感知"查询（如"上周状态"）。
- 后端支持 **Neo4j / FalkorDB / Amazon Neptune / Kuzu（deprecated）** 等图数据库或图服务；默认文档仍以图数据库体系为核心。
- License：**Apache-2.0**。
- 对 EnerGraph：虽然不再是"只支持 Neo4j"，但依然引入图数据库/图服务、LLM 抽取流水线和图索引运维，明显重于本期所需。**除非未来确需多跳时序推理、事实溯源和图遍历，再单独评估**。

### 3.2 Zep（getzep/zep）

- 原开源记忆服务器，后转向**图架构**（Graphiti 驱动）。
- **已转向云服务 SaaS**：开源版（CE）维护与 License 状态需核实（历史上 CE 许可有过变更，企业商用前必须确认）。
- 对 EnerGraph：云导向 + 重型依赖，**当前不推荐**。

### 3.3 轻量化部署模式

- **Graphiti**：有 FalkorDB 等相对轻的后端选择，但仍属于图数据库部署形态；对本期"Postgres 单实例承载 L1/L2"目标来说过重。
- **Zep CE**：走向 SaaS，开源版定位模糊。
- 两者都**不符合** EnerGraph"轻量化 + 本地 + 本期不引入图数据库体系"的约束。

### 3.4 国内方案

- 调研中断，未找到成熟的、值得单独推荐的开源国内记忆框架。EnerGraph 已用 ChromaDB（国产友好的开源向量库）做 RAG，可作为长期记忆向量层底座。如后续发现成熟国内方案再补充。

---

## 4. 三者对比（LangGraph 1.x 生态适配度）

| 维度 | Mem0 | LangMem | Zep / Graphiti |
|------|------|---------|----------------|
| 成熟度 / 社区 | ✅ ~59k★ 极活跃 | ✅ LangChain 官方，~1.5k★，生态紧但小 | ⚠️ Graphiti Apache-2.0 且社区活跃；Zep 转 SaaS |
| LangGraph 集成深度 | 工具式（节点内调用） | ✅ **原生（store/checkpoint）** | 工具式 + 知识图谱 |
| 部署组件 | OSS 自选向量库+LLM；云托管 | ✅ **复用 LangGraph Postgres** | 图数据库/图服务 + LLM 抽取链路（重） |
| 全本地（数据不出网） | ✅ OSS 可全本地 | ✅ **全本地（自有 PG）** | ✅ 但组件重 |
| 官方 MCP Server | ⚠️ 云端稳定/自托管 sunset | ❌ 无（走 LangGraph Tool） | ❌ 无原生 MCP |
| 中文召回 | ❌ BM25/实体硬编码英文(#4884) | ✅ 取决于 embedder（可控） | ⚠️ 取决于图数据库后端 + LLM 抽取 |
| 重型依赖 | 可选 | ✅ **仅 Postgres（已规划）** | ❌ 图数据库体系（违背轻量化偏好） |
| **适配 EnerGraph** | ⚠️ 可用有代价 | ✅ **最契合** | ❌ 过重 |

---

## 5. EnerGraph 选型建议（结论）

### 推荐：LangGraph 原生记忆 + LangMem（主），Mem0 OSS（备）

**三层记忆架构**（与 AI_CONTEXT 规划一致）：

```
L3 知识检索  → 现有 ChromaDB HVAC RAG（5605 条，保持不变）
L2 长期记忆  → LangGraph store + LangMem（PostgresStore，语义事实/偏好）
L1 短期记忆  → LangGraph checkpoint（PostgresSaver，线程级对话历史）
                  ↑ 共用同一个 Postgres（AI_CONTEXT 近期规划已含 PostgresSaver）
```

### 推荐理由（数据支撑）

1. **原生契合**：EnerGraph 本身就是 LangGraph 1.2 项目，LangMem 是 LangChain 官方记忆层 —— 同源、最低摩擦。
2. **零新增重型依赖**：L1/L2 共用一个 Postgres（PostgresSaver + PostgresStore），而 Postgres 本就在近期规划中；不引入 Neo4j、Milvus、Redis 多件套。
3. **全本地、数据不出网**：满足企业级要求 —— 这正是 Mem0 云端 MCP 的痛点（§1.4）。
4. **中文可控**：embedder 复用 EnerGraph 现有 bge-small-zh，规避了 Mem0 的 BM25/实体英文硬编码问题（§1.6）。
5. **不违反 MCP 优先**：记忆是 Agent 层基础设施，非算法计算引擎，走 LangGraph Tool 合规（见 §0 关键澄清）。

### Mem0 作为备选的场景

- 未来需要更丰富的开箱即用"提取/去重"算法时，可引入 **Mem0 OSS `Memory` 库**（pin 版本）+ 自有 Chroma + 本地 LLM + 自包 MCP 层。
- 触发条件：LangMem 的记忆提取质量不达标，**且** Mem0 的中文 issue（#4884/#5549）已修复，**且** 其本地 MCP 路径稳定。

### 放弃 Zep/Graphiti 的理由

Graphiti 虽已支持 Neo4j 之外的 FalkorDB / Neptune 等后端，但仍属于图数据库体系，违背本期"轻量化、Postgres 单实例优先"目标；Zep 转向托管平台与企业本地化偏好冲突。未来确需多跳时序推理、事实溯源和动态图谱时再单独评估。

### 部署架构图

```
                    ┌─────────────────────────────────────┐
                    │   EnerGraph Agent（LangGraph 1.2）   │
                    │                                     │
                    │  cognitive_parser ── memory_manager │ ← 新增节点（L2 检索/写入）
                    │        │                │           │
                    └────────┼────────────────┼───────────┘
                             │                │
                ┌────────────▼──────┐ ┌───────▼──────────────┐
                │  L1 短期记忆       │ │  L2 长期记忆           │
                │  PostgresSaver     │ │  PostgresStore+LangMem│
                │  (checkpoint)      │ │  (semantic store)    │
                └────────┬───────────┘ └────────┬─────────────┘
                         │     同一 Postgres      │
                         └──────────┬─────────────┘
                                    │
                         ┌──────────▼──────────┐
                         │  PostgreSQL (+pgvector)│ ← 外部部署，仓库不内置 Compose
                         └──────────────────────┘

  L3 知识检索：ChromaDB（保持不变，独立）
  记忆 Tool：search_memory / save_memory → 注册到 TOOL_REGISTRY（Pydantic I/O）
```

### 需后续补齐的数据缺口（开发验证）

- [x] LangMem 最新版本号 / star 数 / 最近 release（2026-06-25 已补齐）
- [ ] `langmem` 与 `langgraph` 1.2 的项目内安装兼容性（Task 1/3 实测）
- [ ] `AsyncPostgresStore` + pgvector 的连接串、索引维度、表初始化配置示例（Task 2/3 实测）
- [ ] Zep CE 当前 License（若未来考虑）

> **数据缺口声明**：本报告的 Mem0 / LangMem / Graphiti 关键事实均已做一手复核；剩余缺口集中在项目内兼容性验证与未来才会考虑的 Zep CE 商用许可核实。选型结论主要依赖 Mem0 的 MCP 云端化/中文英文硬编码问题 + LangMem 的 LangGraph 原生契合性。
