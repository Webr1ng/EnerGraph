# EnerGraph（青山大模型）— 自演化智能能源 Agent 项目上下文

## 项目状态
**当前阶段**: Phase 1-4 完成 ✅ | Phase 7 完成 ✅ | **多智能体架构重构完成 ✅** | **Phase 6 数据导出进行中 🔧（能耗/报警 CSV 导出 ✅，图表可视化 ⏸️ 延后）** | **记忆模块代码完成、待真实 PostgreSQL 验收 🔧（L1/L2 持久化 + 自动抽取 + upsert）**
**最后更新**: 2026-07-02
**项目性质**: 企业级落地方案，南京福加智能科技有限公司内部项目  
**GitHub**: https://github.com/Webr1ng/EnerGraph.git  
**GitLab**: git@172.16.3.160:ai-group/energraph.git  
**Python 环境**: conda `energraph` / Python 3.11（LangGraph 要求 ≥3.10）

**文档分工**：
- `AI_CONTEXT.md`：项目状态、技术架构、目录清单、工具/技能注册表、阶段进度的单点真相
- `PRD.md`：产品定位、用户画像、用例、非功能需求、产品红线
- `docs/TEAM_COLLABORATION_GUIDE.md`：多人并行开发流程、冲突规避、MR/Review 操作指南
- `CLAUDE.md`：强制规范与红线（代码、Git、测试、文档维护）

---

## 1. 项目背景与定位

### 1.1 公司背景

**南京福加智能科技有限公司**是一家专注于暖通控制系统的企业，主要产品为能碳管理平台（已在福加本厂部署）。平台覆盖：冷水机房监控、光储协同、负荷预测、主动寻优（强化学习）、数据公信（区块链上链）等模块。

本项目是福加能碳管理平台的 **AI Agent 层**（即青山大模型的 Agent 实现），最终目标是为福加负责建设的各类厂区、地铁站、商业建筑提供智能化能源调度与能碳管理服务。EnerGraph 的第一个业务落地身份是 **PowerAI 储能调度智能体**（光伏预测 + 负荷预测 → 综合决策 → 充放电策略）。

### 1.2 项目在 V3.0 五层架构中的定位

EnerGraph 是公司青山大模型 V3.0 **五层架构**中 **第 3 层（决策层）+ 第 4 层（自演化引擎层）** 的代码实现。Agent 不参与热力学运算和数值优化计算，而是作为整个系统的"编排大脑"：

**V3.0 五层架构全景**：

| 层级 | 名称 | 职责 | 本项目角色 |
|------|------|------|-----------|
| 第 5 层 | 应用层 | Vue.js 前端 / APP / 语音助手 | 不直接负责（前端团队） |
| 第 4 层 | 自演化 Agent 引擎层 | 闭环学习 · 技能工厂 · 记忆中枢 · 多Agent协作 | **未来演进方向**（当前未实现） |
| **第 3 层** | **青山大模型决策层** | **意图理解 → 任务拆解 → MCP工具调度 → 结果整合 → 决策解释** | **当前核心实现**（EnerGraph 本体） |
| 第 2 层 | 算法模型层 | 9个纯计算引擎（预测/诊断/优化），通过 MCP 暴露 | 通过 MCP Client 调用（当前 Mock） |
| 第 1 层 | 数据采集层 | 传感器 → Kafka → InfluxDB | 不直接负责（硬件/运维团队） |

**EnerGraph 作为决策层的三大核心职责**：

| 角色 | 职责 | 对应代码模块 |
|------|------|-------------|
| **意图理解** | 自然语言 / ERP JSON → 结构化任务拆解 | `cognitive_parser` 节点 |
| **工具调度** | 通过 MCP 协议调用算法模型层的计算引擎；通过 REST API 查询福加运营数据 | `v3_engine_router` 节点 + Tools |
| **决策解释** | 算法模型返回的数值结果 → 用户可理解的 Markdown 报告 | `interpreter_generator` 节点 |

**与多智能体矩阵的关系**：公司规划的多个智能体（PowerAI 储能调度、能效诊断、碳管理、微电网、充电调度）并非独立的软件系统，而是**同一套 EnerGraph 决策层代码的不同业务配置**——共享同一套 LangGraph 编排框架和 MCP 工具调用机制，只是各自挂载不同的 Skill（调用不同的算法模型）和不同的 Prompt。EnerGraph 当前的第一个业务身份是 PowerAI。

### 1.3 项目目标与演进路线

```
已完成的阶段：
  Phase 1 ✅  HVAC 专家问答 + ReAct 循环 + 流式前端
  Phase 2 ✅  FastAPI SSE + UIAction 页面跳转 + Java 后端工具
  Phase 3 ✅  RAG 质量优化（相关度阈值 + 拒答 + 引用来源）
  Phase 4 ✅  福加运营数据真实对接（13 个监控/范围查询工具 + Token 自动刷新）
  Phase 7 ✅  多意图识别与拆分执行
  Skills 基类 ✅  BaseSkill 抽象基类 + 生命周期钩子
  API 交付 ✅   CORS + 鉴权 + 前端对接文档

当前阶段（**多智能体架构重构 + PowerAI 核心能力建设**）：
  ─────────────────────────────────────────────
  ✅ **多智能体 Subgraph 架构重构**（2026-06-15 完成）
    - 创建 BaseAgent 抽象基类 + AGENT_REGISTRY 注册表
    - 重构 HVAC/UI Router/PowerAI 为独立 Agent 子图
    - Prompt 按 Agent 拆分（`prompts/*.yaml`），零冲突
    - 编写团队协作开发指南（TEAM_COLLABORATION_GUIDE.md）
  
  ★ 接入算法模型层的预测/优化模型（通过 MCP 协议）
    光伏出力预测 → 电负荷预测 → 冷负荷预测 → 储能调度优化
    - 过渡期约定：MCP Server 正式接入前，算法预测相关数据若已有福加网页后端接口，按普通 REST 数据工具调用；不得调用未注册 MCP 工具或编造预测/优化结果
  ★ 实现综合决策 Skill：多预测结果融合 → 生成 2-3 个候选调度方案
  ★ 启用 LangGraph 持久化（PostgresSaver）+ Human-in-the-Loop
  ★ **记忆模块**（`feature/memory-system` 分支开发中）：三层记忆架构
    - L1 短期记忆 = LangGraph checkpoint（PostgresSaver，线程级对话历史）
    - L2 长期记忆 = LangGraph `PostgresStore`（连接池 + setup + 确定性 key 原子 upsert；跨会话语义记忆，按 env/site_id/agent_id namespace 隔离）；本地可回退 InMemory/demo
    - 多智能体记忆策略：底层共用同一 PostgreSQL / LangGraph Store，逻辑上按 `env/site_id/agent_id/memory_type` 隔离；默认私有，站点事实/用户通用偏好/安全约束显式写入 `global` 或 `site` namespace 共享，`device_state`/`decision_history` 默认不跨 Agent 共享
    - L3 知识检索 = 现有 ChromaDB HVAC RAG（保持不变）
    - 工程约束：PostgresSaver/PostgresStore 首次启用需 `.setup()`；可用迁移账号初始化后关闭自动 setup；记忆写入带 `memory_type/source_thread_id/site_id/confidence/valid_until` 等元数据，`device_state` 临时状态必须有 TTL
    - 自动抽取：可配置 LLM 结构化抽取（默认关闭）；`MemoryCandidate` 记录 `source/retrievable/user_confirmed/memory_key`，代码闸门只接受用户明确表达且不可重新查询的信息，`device_state` 不自动写入；用户偏好按稳定 `user_id` 跨会话保存并按 `memory_key` 原地更新
    - 选型结论：**LangMem 为主 / Mem0 OSS 为备 / 放弃 Zep·Graphiti**（本期避免引入图数据库体系）
    - 详细规划见 `docs/research_memory_frameworks.md` + `docs/plan_memory_module.md`

近期规划：
  ★ 记忆模块   三层记忆基础设施已接入（checkpoint + store/LangMem + ChromaDB），Postgres 单实例承载 L1/L2
  RAG 升级   BGE-M3 + BM25 混合检索 + BGE-Reranker 重排序
  MCP 标准化  现有 Tools 逐步迁移为 MCP Server / Client 架构；预测/优化 MCP 正式接入前，PowerAI 暂以福加网页后端数据工具作为过渡数据源
  Phase 5    语音助手（Whisper STT + TTS）⏸️ **延后**（优先级让位记忆模块）
  Phase 6    数据导出（表格 + CSV 下载）🔧 **进行中**（能耗/报警导出 ✅，图表可视化 ⏸️ 延后）

中长期演进（对齐公司 V3.0 路线图）：
  记忆系统升级  反思记忆（LangMem reflection / Mem0 OSS）+ 闭环学习 + 知识图谱多跳推理
  闭环学习   Event Sourcing 反馈采集 + 效果评估 + 经验提炼 + 棘轮机制
  多Agent    A2A 协议 + 技能共享 + 跨Agent经验复用
  Guardrails NeMo Guardrails + 行为沙箱 + 权限分级
  知识图谱   Neo4j 动态知识图谱 + GraphRAG（待多跳推理需求触发再评估）
```

---

## 2. 技术架构

### 2.1 技术栈

| 类别 | 技术 | 说明 |
|------|------|------|
| 核心框架 | LangGraph 1.2（`requirements.txt` 锁定 `>=1.2,<2`） | ReAct 状态图，支持 token 级流式 |
| LLM | DeepSeek V4 / OpenAI / Claude | `LLM_PROVIDER` 环境变量一键切换 |
| Embedding | BAAI/bge-small-zh-v1.5（SentenceTransformers） | 中文优化，本地模型（计划升级为 BGE-M3） |
| 向量库 | ChromaDB（本地持久化） | `data/hvac_knowledge/`，5605 条 HVAC 语料；作为 **L3 知识检索层**保持不变 |
| 记忆-短期（L1） | LangGraph checkpoint（PostgresSaver，`langgraph-checkpoint-postgres>=3.1,<4`） | 线程级对话历史 + AgentState 快照（`feature/memory-system`）；`psycopg[binary,pool]` 必须安装，避免缺 `libpq` 导入失败 |
| 记忆-长期（L2） | LangGraph PostgresStore + LangMem（`langmem==0.0.30`） | 生产连接池持久化，按 `env/site_id/agent_id` namespace 隔离；确定性 key 原子 upsert；带时效元数据；备选 Mem0 OSS |
| 记忆-知识（L3） | ChromaDB HVAC RAG | 即上方向量库，保持不变 |
| 持久化数据库 | PostgreSQL + pgvector（外部提供，可选） | L1 checkpoint 与 L2 store 生产环境共用单实例；本地联调默认使用内存回退 + demo 文件落盘 |
| 数据验证 | Pydantic 2.x | Tool I/O 强类型；AgentState 用 TypedDict |
| 工具协议 | MCP（计划引入） | 算法模型通过 MCP Server 暴露，Agent 通过 MCP Client 调用 |
| 可观测性 | LangSmith | 执行链路追踪（`LANGCHAIN_TRACING_V2=true`） |
| 前端（演示） | Streamlit 1.39 | token 级流式展示 ReAct 思考过程 |
| API 服务 | FastAPI + uvicorn | CORS + 可选 Bearer Token 鉴权 + SSE 流式，交付前端对接 |
| 配置 | python-dotenv + PyYAML | Prompt 集中管理（prompts/ 目录按 Agent 拆分）、版本控制、环境隔离 |
| 加密 | pycryptodome | RSA 加密（福加 Token 自动刷新） |
| Python | 3.11 | |

### 2.2 LangGraph ReAct 状态图

```
用户输入
    │
    ▼
┌─────────────────────┐
│  cognitive_parser   │  LLM 分析意图 → 选择工具（streaming=True）
└──────────┬──────────┘
           │
    有 tool_calls?
    ┌──YES──┴──NO──┐
    ▼              ▼
┌──────────────┐  ┌──────────────────────┐
│v3_engine_    │  │ interpreter_generator│ → END
│router        │  │ 生成 Markdown 报告    │
│（执行工具）   │  └──────────────────────┘
└──────┬───────┘
       │
       └──→ cognitive_parser（循环，最多 max_iterations 次）
```

**流式输出**: `graph.stream(stream_mode=["updates","messages"])` 逐 token 推送，前端实时展示思考过程。

### 2.3 LLM 供应商切换

`.env` 中设置 `LLM_PROVIDER`，无需改代码：

```ini
LLM_PROVIDER=deepseek   # deepseek-v4-pro / deepseek-v4-flash
# LLM_PROVIDER=openai   # gpt-4o
# LLM_PROVIDER=anthropic # claude-sonnet-4-6
```

DeepSeek V4 注意：`thinking` 模式已禁用（`extra_body={"thinking":{"type":"disabled"}}`），避免 tool calling 时 `reasoning_content` 报错。

### 2.4 Tools vs Skills 分工与工具接入方式

```
Tools（原子执行层）= 确定性函数，强类型 I/O，不含 Prompt
  → src/tools/：fetch_cop_data, query_hvac_knowledge, navigate_to_page ...

Skills（业务推理层）= 专属 Prompt + SOP 流程 + Tools 编排
  → src/skills/：HVACExpertSkill, UIRouterSkill, EnergyDispatchSkill ...

Graph Nodes（调度层）= cognitive_parser 识别技能 → Skill 编排 Tools
  → 节点代码保持精简，不含业务逻辑
```

**工具接入方式（两类）**：

| 类型 | 接入方式 | 工具示例 | 说明 |
|------|---------|---------|------|
| **算法模型工具** | MCP 协议（计划） | 光伏预测、电负荷预测、冷负荷预测、储能调度优化、设备健康诊断 | 算法团队将模型封装为 MCP Server（FastAPI + JSON Schema），Agent 通过 MCP Client 调用。热插拔，标准化接口 |
| **运营数据工具** | REST API（当前） | fetch_cop_data、fetch_energy_summary、fetch_energy_range、fetch_alarm_history、fetch_pv_forecast、fetch_load_forecast、fetch_electricity_forecast、fetch_pv_forecast_range、fetch_load_forecast_range、fetch_electricity_forecast_range 等 19 个福加监控/预测/范围查询工具 | 直接调用福加 Java 后端已有 API，参数解析和 Token 刷新在 Tool 代码内处理 |

> **注意**：算法模型工具当前尚未接入（Agent 侧接口适配层已就绪，待算法团队 MCP Server 就绪后即可调用）。运营数据工具（福加 API）保持 REST API 方式不变。



```
EnerGraph/
├── CLAUDE.md                  # 协作规范（每次 session 自动加载，优先级最高）
├── AGENTS.md                  # OpenAI Codex CLI 入口指令（引用 CLAUDE.md）
├── AI_CONTEXT.md              # 本文件（项目单点真相）
├── CHANGELOG.md               # 完整变更历史记录
├── PRD.md                     # 产品需求文档（用户场景 + 功能定义）
├── MCP_INTERFACE_SPEC.md      # MCP 接口契约（9 个算法模型接口规范）
├── .env.example               # 环境变量模板
├── requirements.txt
├── run.py                     # API 服务启动脚本（python run.py / python run.py --prod）
├── config/
│   ├── agent_config.yaml      # 默认配置（.env 优先覆盖）
│   └── routes.yaml            # 前端路由注册表（24 可访问 + 10 受限）
├── docs/                      # 各阶段开发 plan + 项目文档
│   ├── plan_skills_refactor.md      # Skills 架构重组方案（跨 Phase 基础设施）
│   ├── plan_skills_base_class.md    # Skills 基类升级（BaseSkill + 生命周期管理）
│   ├── plan_phase2_action_agent.md  # Action Agent：FastAPI SSE + UIAction + Java 工具
│   ├── plan_phase3_rag.md           # RAG 质量优化
│   ├── plan_phase4_realapi.md       # 真实 API 对接
│   ├── plan_phase5_voice.md         # 语音助手
│   ├── plan_phase6_export.md        # 数据导出（统一 CSV 模板，图表可视化延后）
│   ├── plan_phase7_multi_intent.md         # 多意图识别与拆分执行
│   ├── plan_memory_module.md               # 【记忆模块】开发计划（三层记忆 + 6 个 Task）
│   ├── research_memory_frameworks.md       # 【记忆模块】选型调研报告（Mem0/LangMem/Zep）
│   ├── memory_module_implementation_guide.md # 【记忆模块】功能实现说明与接手指南
│   ├── postgres_memory_operations.md # 【记忆模块】生产 PostgreSQL 部署、迁移、备份恢复手册
│   ├── plan_fix_navigation_routes.md       # Agent 导航功能修复计划
│   ├── frontend_backend_alignment.md       # 前后端对接文档
│   ├── frontend_integration_guide.md      # 前端对接指南（Vue.js 示例 + TypeScript 类型 + SSE）
│   ├── REFACTORING_SUMMARY.md             # 多智能体架构重构总结
│   ├── TEAM_COLLABORATION_GUIDE.md        # 团队协作开发规范（多智能体并行开发指南）
│   ├── REPORT_2026_06.md                  # 管理层汇报文档（2026-06）
│   └── EnerGraph_API接口说明.md           # API 接口说明
└── src/
    ├── config/
    │   ├── settings.py        # 配置加载（LLM_PROVIDER / DEEPSEEK_MODEL 等）
    │   └── prompts/           # 【唯一入口】System Prompt 按 Agent 拆分管理
    │       ├── _shared.yaml        # 共享片段（回答原则/跳转规则）
    │       ├── main_graph.yaml     # 主图节点 Prompt
    │       ├── hvac_expert.yaml    # HVAC Agent 专属
    │       ├── ui_router.yaml      # UI Router Agent 专属
    │       └── powerai.yaml        # PowerAI Agent 专属
    ├── schemas/
    │   ├── v3_engine.py       # Pydantic 模型：ConstraintMatrix / PhysicsResidual /
    │   │                      #   HVACKnowledgeResult / IntentItem（Phase 7）
    │   ├── action_agent.py    # PageContext / ActionAgentInput / UIAction（Phase 2）
    │   ├── data_card.py       # ColumnDef / TableData / DownloadInfo / DataCard（Phase 6 导出）
    │   └── memory.py          # MemoryQuery / MemoryItem / MemorySearchResult / MemoryWriteResult
    ├── skills/                # 业务技能层（Prompt + SOP + Tools 编排，均继承 BaseSkill）
    │   ├── __init__.py        # SKILL_REGISTRY + SKILL_DESCRIPTIONS + get_skill() + get_matched_skills()
    │   ├── base_skill.py      # BaseSkill 抽象基类（execute / before / after 钩子）
    │   ├── hvac_expert_skill.py     # HVAC 专家问答（Phase 3 完善）
    │   ├── energy_dispatch_skill.py # 能源调度分析（Phase 4 完善）
    │   ├── ui_router_skill.py       # 页面跳转 + 数据可视化/导出（Phase 2）
    │   └── v3_interpreter_skill.py  # V3 数据解读报告
    ├── tools/                 # 工具层（原子执行层）
    │   ├── __init__.py        # TOOL_REGISTRY + TOOL_SCHEMAS（LLM function calling 用）
    │   ├── parse_intent.py    # 意图解析 → ConstraintMatrix
    │   ├── query_hvac_knowledge.py # HVAC RAG 检索（真实，ChromaDB）
    │   ├── navigate_to_page.py   # 页面跳转 → UIAction（Phase 2）
    │   ├── java_backend.py       # 福加运营数据工具：19 个真实 REST API + Token 自动刷新（Phase 4.3 + Phase 6 范围查询 + 光伏/冷负荷/电负荷预测 loadForecast）
    │   ├── export_data.py        # export_data_table 通用 CSV 导出 → DataCard（Phase 6）
    │   └── memory_ops.py         # search_memory / search_relevant_memory / save_memory（L2 长期记忆工具）
    ├── utils/
    │   └── fuca_token_refresher.py  # 福加 Token 自动刷新（RSA 加密登录 + 401 重试）
    ├── graph/
    │   ├── state.py           # AgentState（TypedDict + Annotated，含 page_context/pending_actions/message_metadata）
    │   ├── nodes.py           # 三个节点函数（v3_engine_router 含 Skill 调度分发）
    │   ├── edges.py           # should_continue 条件路由
    │   ├── builder.py         # 图编译，graph 全局单例
    │   └── agents/            # 多智能体 Subgraph 模块
    │       ├── base_agent.py       # BaseAgent 抽象基类
    │       ├── __init__.py         # AGENT_REGISTRY 注册表
    │       ├── hvac_expert/        # HVAC 专家 Agent 子图
    │       ├── ui_router/          # UI Router Agent 子图
    │       └── powerai/            # PowerAI 储能调度 Agent 子图（骨架）
    ├── pipelines/
    │   └── rag_ingest.py      # HVAC 语料入库（5605 条，bge-small-zh-v1.5）
    ├── services/
    │   └── api.py             # FastAPI：GET /health + POST /invoke + POST /stream (SSE)
    ├── memory/               # 【记忆模块】L2 长期记忆封装（namespace + TTL + fallback）
    │   ├── extractor.py      # LLM 结构化长期记忆抽取（JSON → MemoryExtractionResult）
    │   └── store.py          # L2 长期记忆客户端封装（单例 + env/site/agent namespace）
    ├── frontend/
    │   └── app.py             # Streamlit 演示前端（token 级流式）
    └── tests/
        ├── __init__.py        # 测试包初始化
        ├── test_action_agent.py  # /stream 端点集成测试（Phase 2 T6，9 passed）
        ├── test_base_skill.py    # BaseSkill 基类契约测试（Skills 基类，15 passed）
        ├── test_hvac_quality.py  # RAG 质量测试（Phase 3 T5，19 passed）
        ├── test_multi_intent.py    # 多意图识别测试（Phase 7 T5，16 passed）
        ├── test_ui_router_skill.py # 路由匹配单元测试（Phase 4.3，4 passed）
        ├── test_agent_flow.py    # Agent 流程测试（1 passed）
        ├── test_customer_scenarios.py  # 客户场景测试（1 passed）
        ├── test_fuca_api.py      # 福加 API 集成测试（1 passed）
        ├── test_memory_store.py     # 记忆 store 测试（namespace/TTL/error）
        ├── test_memory_tools.py     # search_memory/search_relevant_memory/save_memory 工具测试
        ├── test_memory_isolation.py # 多环境/站点/Agent 记忆隔离测试
        ├── test_memory_extraction.py # 记忆自动抽取与质量闸门测试
        ├── test_memory_relevant_search.py # 跨 scope 聚合检索测试
        ├── test_data_export.py    # Phase 6 数据导出单测（export/range/alarm/endpoint/SSE，24 passed）
        └── test_navigation.py    # 导航功能脚本（无 pytest 用例）
---

## 4. 工具注册表（Tools）与技能注册表（Skills）

### 4.1 Tools — 原子执行层

| 工具名 | 状态 | 对接引擎 | 输出模型 |
|--------|------|----------|----------|
| `parse_business_intent` | 已实现 | N/A（纯 LLM） | `ConstraintMatrix` |
| `query_hvac_knowledge` | **真实** | ChromaDB RAG | `HVACKnowledgeResult` |
| `navigate_to_page` | ✅ 已实现 | N/A（状态变更） | `UIAction`（Phase 2） |
| `fetch_cop_data` | **真实** ✅ | 福加 API | `COPData`（Phase 4.2） |
| `fetch_energy_summary` | **真实** ✅ | 福加 API | `EnergySummary`（Phase 4.1） |
| `fetch_active_alarms` | **真实** ✅ | 福加 API | `AlarmList`（Phase 4.2） |
| `fetch_carbon_info` | **真实** ✅ | 福加 API | `CarbonInfo`（Phase 4.2） |
| `fetch_photovoltaic_monthly` | **真实** ✅ | 福加 API | dict（月度列表）（Phase 4.2） |
| `fetch_photovoltaic_daily` | **真实** ✅ | 福加 API | dict（日度发电量+峰值功率）（Phase 4.2） |
| `fetch_pv_forecast` | **真实** ✅ | 福加 API（loadForecast 微服务，500 自动刷新 Token） | `ForecastResult`（energyType=pv，预测vs实际+准确率+天气，对应 /analysis/pv-forecast） |
| `fetch_load_forecast` | **真实** ✅ | 福加 API（loadForecast 微服务，500 自动刷新 Token） | `ForecastResult`（energyType=load，预测vs实际+平均偏差+天气+当前/预测/下小时负荷，对应 /analysis/load-forecast） |
| `fetch_electricity_forecast` | **真实** ✅ | 福加 API（loadForecast 微服务，500 自动刷新 Token） | `ForecastResult`（energyType=electricity，预测vs实际+平均偏差+天气+当前/预测/下小时负荷，对应 /analysis/electricity-forecast） |
| `fetch_energy_usage` | **真实** ✅ | 福加 API | `EnergyUsage`（Phase 4.2） |
| `fetch_device_rank` | **真实** ✅ | 福加 API | `DeviceRank`（Phase 4.2） |
| `fetch_environment_params` | **真实** ✅ | 福加 API | `EnvironmentParams`（Phase 4.2） |
| `fetch_efficiency_calendar` | **真实** ✅ | 福加 API | `EfficiencyCalendarDay/Month`（Phase 4.2） |
| `fetch_efficiency_detail` | **真实** ✅ | 福加 API | dict（通用能效查询，8 种参数）（Phase 4.2） |
| `search_memory` | ✅ 已实现 | L2 LangGraph store / InMemory fallback | `MemorySearchResult` |
| `search_relevant_memory` | ✅ 已实现 | L2 LangGraph store / InMemory fallback | `MemorySearchResult` |
| `save_memory` | ✅ 已实现 | L2 LangGraph store / InMemory fallback | `MemoryWriteResult` |
| `fetch_energy_range` | ✅ 已实现（Phase 6） | 福加 API（逐日复用 fetch_energy_summary） | dict（items + total_days）（Phase 6） |
| `fetch_alarm_history` | ✅ 已实现（Phase 6） | 福加 API（listHisAlarms） | dict（items + total）（Phase 6） |
| `fetch_pv_forecast_range` | ✅ 已实现（Phase 6） | 福加 API（逐日复用 loadForecast realTime/changeRealTime，energyType=pv） | dict（items + total_days）（Phase 6，供导出） |
| `fetch_load_forecast_range` | ✅ 已实现（Phase 6） | 福加 API（同上，energyType=load） | dict（items + total_days）（Phase 6，供导出） |
| `fetch_electricity_forecast_range` | ✅ 已实现 | 福加 API（同上，energyType=electricity） | dict（items + total_days）（供导出） |
| `export_data_table` | ✅ 已实现（Phase 6） | N/A（本地 CSV 文件） | `DataCard`（Phase 6） |

### 4.2 Skills — 业务推理层

| 技能名 | 状态 | 调用 Tools | 完善阶段 |
|--------|------|-----------|---------|
| `ui_router` | ✅ SOP 已实现 | navigate_to_page + 19 个福加监控/预测/范围查询工具 + export_data_table | Phase 2 → Phase 6 扩展 → 光伏/冷负荷/电负荷预测 |
| `hvac_expert` | ✅ 已实现 | query_hvac_knowledge | Phase 3 ✅ |
| `energy_dispatch` | 骨架 | parse_intent；未来接入 MCP 预测/优化模型 | Phase 4 → PowerAI 核心 |
| `v3_interpreter` | 骨架 | 无（纯 LLM） | Phase 2-4 逐步迁移 |

**HVAC 知识库**: 5605 条语料，覆盖规范查询、能效计算、故障诊断、节能优化，含地铁站/商业项目专项。

---

## 5. 开发阶段与工作顺序

| 阶段 | 内容 | 状态 | Plan |
|------|------|------|------|
| Phase 1 | ReAct 循环 + HVAC RAG + DeepSeek V4 + 流式前端 | ✅ 完成 | — |
| Phase 2 | Action Agent：FastAPI SSE + UIAction 跳转信号 + Java 后端工具 | ✅ 完成 | `docs/plan_phase2_action_agent.md` |
| Skills 基类 | BaseSkill 抽象基类 + 生命周期钩子 + 统一调度 | ✅ 完成 | `docs/plan_skills_base_class.md` |
| Phase 3 | RAG 质量优化（相关度阈值 + 拒答 + 引用来源） | ✅ 完成 | `docs/plan_phase3_rag.md` |
| Phase 4 | Mock → 真实对接：福加 API ✅ + 算法模型层 MCP 对接（接口适配层已就绪，待算法模型交付后接入） | 大部分完成（福加 11 API ✅；算法模型 MCP 接口契约已定义） | `docs/plan_phase4_realapi.md` + `docs/plan_phase4_realapi_batch.md` |
| Phase 5 | 语音助手（Whisper STT + TTS） | ⏸️ **延后**（优先级让位记忆模块） | `docs/plan_phase5_voice.md` |
| Phase 6 | 数据导出（表格 + CSV 下载，统一模板） | 🔧 **进行中**（能耗/报警导出 ✅；图表可视化 ⏸️ 延后） | `docs/plan_phase6_export.md` |
| Phase 7 | 多意图识别与拆分执行（单输入多意图 + 分段报告） | ✅ 完成 | `docs/plan_phase7_multi_intent.md` |
| **记忆模块** | 三层记忆：L1 PostgresSaver + L2 PostgresStore/search/save/upsert + namespace/TTL/隔离 + LLM 结构化自动抽取 + L3 ChromaDB；本地可用 demo，生产使用外部 PostgreSQL | 🔧 **本机 PostgreSQL 验收通过，待服务器验收**（L1/L2 建表、重连读取、确定性 upsert 已验证） | `docs/plan_memory_module.md` + `docs/memory_module_implementation_guide.md` + `docs/postgres_memory_operations.md` |
| API 交付 | CORS + 鉴权 + 启动脚本 + 前端对接文档（Vue.js） | ✅ 完成 | `docs/frontend_integration_guide.md` |

**阶段顺序可以调整**，plan 文件相互独立。Phase 4 依赖算法团队 API 就绪，可与 Phase 3 并行。Phase 5 只依赖 Phase 2（API 层）。Phase 6 依赖 Phase 2，可与 Phase 3-5 并行。Phase 7 依赖 Phase 2，可与 Phase 3-6 并行。Skills 基类方案建议在 Phase 3 之前完成。**记忆模块**与算法模型 MCP 对接可并行推进；Phase 5/6 因优先级让位记忆模块而延后。

**每个 session 开发流程**:
```
读 CLAUDE.md（自动）+ AI_CONTEXT.md + docs/plan_phaseX.md
→ 执行一个子任务（T1/T2/...）
→ commit
→ session 结束
```

---

## 6. 变更日志（近期摘要）

> 完整变更记录见 `CHANGELOG.md`。

| 日期 | 变更 | 作者 |
|------|------|------|
| 2026-07-02 | **[fix]+[config]+[test] 回答格式偏好双层识别**：Prompt 区分“运营数据本身”和“如何回答/展示数据”，代码仅在长期表达+回答行为+格式属性同时命中时纠正 LLM 误判或补建偏好候选；能耗/COP/光伏业务词不再导致格式偏好被拒，实时数据和普通查询仍不保存。全量 237 passed / 6 skipped。 | 周溥林 |
| 2026-07-02 | **[config] hotfix 加「严禁编造数据」红线**：用户反馈 Agent 问「导出7天 COP」时因无 `fetch_cop_range`，LLM 编造 7 天 COP/制冷量/用电量假数据 + 调 `export_data_table` 生成假 CSV（06-30 COP=0 但制冷 3672 除零破绽）。核实 `fetch_cop_data` 无 date 参数/无制冷量用电量字段/无 range 版，工具层拿不到→纯幻觉。根因：cognitive_parser 缺「无工具不得编造」约束。**修复**：`_shared.yaml` `answer_principles` 增红线——数值必须来自已调工具真实返回值；无对应工具时如实告知「暂不支持」，绝不编造/不调 export 生成假 CSV；无数据说「暂缺接口」。注入所有 Agent。用户授权直接 main 提交 | 魏博源 |
| 2026-07-02 | **[fix]+[test] 全面审查修复记忆意图边界**：“请记住我的偏好”稳定进入写入，“你记住了哪些偏好？”稳定进入查询；普通业务修改/未来问题不误判。mypy、git fsck、214 项测试通过。 | 周溥林 |
| 2026-07-02 | **[config] requirements 记忆依赖复核**：现有 PostgresSaver/PostgresStore、psycopg binary/pool、LangMem 版本约束已覆盖最新实现，无需新增依赖；补充职责注释。 | 周溥林 |
| 2026-07-02 | **[schemas]+[frontend] API 透传稳定 user_id**：`/invoke`、`/stream` 支持稳定用户 ID，生产多用户偏好不再全部落入 `default_user`；前端需传登录用户 ID。 | 周溥林 |

> 更早历史见 `CHANGELOG.md` 或 `git log`。

---

**下一步**: 
1. **记忆模块收尾**：在真实 PostgreSQL 上验收 checkpoint 恢复、L2 跨进程读写/并发 upsert、备份恢复与 LangMem 抽取质量；验收后生产设置 `MEMORY_USE_POSTGRES_STORE=true`
2. 与算法团队协调 MCP 接口规范，准备接入光伏/负荷/冷负荷预测模型（可与记忆模块并行）
3. 完成 energy_dispatch Skill（PowerAI 综合决策核心）
4. RAG 升级（BGE-M3 混合检索）
5. Phase 5 语音助手 ⏸️ 延后；Phase 6 数据导出 🔧 进行中（能耗/报警 CSV 导出 ✅，图表可视化 ⏸️ 延后），`feature/phase6-export` 分支待 PR 合 main
