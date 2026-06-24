# EnerGraph（青山大模型）— 自演化智能能源 Agent 项目上下文

## 项目状态
**当前阶段**: Phase 1-4 完成 ✅ | Phase 7 完成 ✅ | **多智能体架构重构完成 ✅**  
**最后更新**: 2026-06-24
**项目性质**: 企业级落地方案，南京福加智能科技有限公司内部项目  
**GitHub**: https://github.com/Webr1ng/EnerGraph.git  
**GitLab**: git@172.16.3.160:ai-group/energraph.git  
**Python 环境**: conda `energraph` / Python 3.11（LangGraph 要求 ≥3.10）

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
  Phase 4 ✅  福加运营数据真实对接（11 个 API + Token 自动刷新）
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
  ★ 实现综合决策 Skill：多预测结果融合 → 生成 2-3 个候选调度方案
  ★ 启用 LangGraph 持久化（PostgresSaver）+ Human-in-the-Loop

近期规划：
  Phase 5    语音助手（Whisper STT + TTS）
  Phase 6    数据可视化 + 报表导出（表格/图表/CSV 下载）
  RAG 升级   BGE-M3 + BM25 混合检索 + BGE-Reranker 重排序
  MCP 标准化  现有 Tools 逐步迁移为 MCP Server / Client 架构

中长期演进（对齐公司 V3.0 路线图）：
  记忆系统   Redis 工作记忆 + Milvus 短期记忆 → Neo4j 长期记忆 + ES 反思记忆
  闭环学习   Event Sourcing 反馈采集 + 效果评估 + 经验提炼 + 棘轮机制
  多Agent    A2A 协议 + 技能共享 + 跨Agent经验复用
  Guardrails NeMo Guardrails + 行为沙箱 + 权限分级
  知识图谱   Neo4j 动态知识图谱 + GraphRAG
```

---

## 2. 技术架构

### 2.1 技术栈

| 类别 | 技术 | 说明 |
|------|------|------|
| 核心框架 | LangGraph 1.2 | ReAct 状态图，支持 token 级流式 |
| LLM | DeepSeek V4 / OpenAI / Claude | `LLM_PROVIDER` 环境变量一键切换 |
| Embedding | BAAI/bge-small-zh-v1.5（SentenceTransformers） | 中文优化，本地模型（计划升级为 BGE-M3） |
| 向量库 | ChromaDB（本地持久化） | `data/hvac_knowledge/`，5605 条 HVAC 语料（计划升级为 Milvus） |
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
| **运营数据工具** | REST API（当前） | fetch_cop_data、fetch_energy_summary 等 11 个福加监控工具 | 直接调用福加 Java 后端已有 API，参数解析和 Token 刷新在 Tool 代码内处理 |

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
│   ├── plan_phase6_visualization_export.md  # 数据可视化 + 报表导出
│   ├── plan_phase7_multi_intent.md         # 多意图识别与拆分执行
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
    │   └── action_agent.py    # PageContext / ActionAgentInput / UIAction（Phase 2）
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
    │   └── java_backend.py       # 福加运营数据工具：11 个真实 REST API + Token 自动刷新（Phase 4.3）
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
| `fetch_energy_usage` | **真实** ✅ | 福加 API | `EnergyUsage`（Phase 4.2） |
| `fetch_device_rank` | **真实** ✅ | 福加 API | `DeviceRank`（Phase 4.2） |
| `fetch_environment_params` | **真实** ✅ | 福加 API | `EnvironmentParams`（Phase 4.2） |
| `fetch_efficiency_calendar` | **真实** ✅ | 福加 API | `EfficiencyCalendarDay/Month`（Phase 4.2） |
| `fetch_efficiency_detail` | **真实** ✅ | 福加 API | dict（通用能效查询，8 种参数）（Phase 4.2） |
| `fetch_energy_range` | 📋 待实现（Phase 6） | Java 后端 | `List[EnergySummary]`（Phase 6） |
| `fetch_alarm_history` | 📋 待实现（Phase 6） | Java 后端 | `AlarmList`（Phase 6） |
| `export_data_table` | 📋 待实现（Phase 6） | N/A（本地文件） | `DataCard`（Phase 6） |

### 4.2 Skills — 业务推理层

| 技能名 | 状态 | 调用 Tools | 完善阶段 |
|--------|------|-----------|---------|
| `ui_router` | ✅ SOP 已实现 | navigate_to_page + 11 个福加监控工具 | Phase 2 → Phase 4.2 扩展 |
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
| Phase 5 | 语音助手（Whisper STT + TTS） | 待开始 | `docs/plan_phase5_voice.md` |
| Phase 6 | 数据可视化 + 报表导出（表格/图表/CSV 下载） | 待开始 | `docs/plan_phase6_visualization_export.md` |
| Phase 7 | 多意图识别与拆分执行（单输入多意图 + 分段报告） | ✅ 完成 | `docs/plan_phase7_multi_intent.md` |
| API 交付 | CORS + 鉴权 + 启动脚本 + 前端对接文档（Vue.js） | ✅ 完成 | `docs/frontend_integration_guide.md` |

**阶段顺序可以调整**，plan 文件相互独立。Phase 4 依赖算法团队 API 就绪，可与 Phase 3 并行。Phase 5 只依赖 Phase 2（API 层）。Phase 6 依赖 Phase 2，可与 Phase 3-5 并行。Phase 7 依赖 Phase 2，可与 Phase 3-6 并行。Skills 基类方案建议在 Phase 3 之前完成。  

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
| 2026-06-24 | 代码维护清理：移除旧 prompts.yaml 回退、动态生成导航路由说明、清理临时脚本和旧演示路由，默认测试集 63 passed / 6 skipped | 周溥林 |
| 2026-06-22 | AgentState 新增 message_metadata：与 messages 一一对应，记录 timestamp/node/role，为对话日志审计预留接口 | 魏博源 |
| 2026-06-17 | 双路径调度架构澄清 + 管理汇报文档：确立 PowerAI 双路径设计、更新 MCP/PRD 文档、撰写 REPORT_2026_06.md | 魏博源 |
| 2026-06-17 | Action 跳转优化 + 储能数据修复：UIAction 新增 name 字段 + 路由格式标准化 + 修复无工具调用时只有 thinking 没有 text | 魏博源 |
| 2026-06-15 | 重构后代码同步审阅：移除 nodes.py 冗余注入、删除旧 prompts.yaml、修复 v3_interpreter 注释、24 文件头 V3→算法层 | 魏博源 |

> 更早历史见 `CHANGELOG.md` 或 `git log`。

---

**下一步**: 
1. 与算法团队协调 MCP 接口规范，准备接入光伏/负荷/冷负荷预测模型
2. 完成 energy_dispatch Skill（PowerAI 综合决策核心）
3. RAG 升级（BGE-M3 混合检索）+ LangGraph 持久化
4. Phase 5/6 可并行推进
