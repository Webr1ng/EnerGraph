# EnerGraph — 青山大模型 V3.0 决策层

基于 LangGraph 的企业级能源管理 AI Agent，定位为青山大模型 V3.0 五层架构的**第 3 层决策层**（意图理解 → 工具调度 → 决策解释）。集成 HVAC 专业知识库，支持自然语言问答、福加运营数据查询，并通过 FastAPI SSE 接口向前端下发页面跳转控制信号。

## 功能

- **HVAC 专家问答**：5605 条暖通空调专业语料（规范查询、能效计算、故障诊断、节能优化），RAG 检索驱动，低置信度自动拒答，引用来源标注
- **RAG 质量优化**：distance 阈值过滤 + 余弦相似度 MMR 去重（0.98 阈值）+ source_snippets 引用来源
- **多意图识别**：单输入多意图自动拆分，cognitive_parser 并行/串行调度，interpreter 分段报告输出
- **Action Agent**：理解自然语言意图 → 调用 Java 后端监控 API → 流式返回文字总结 + 页面跳转信号
- **Skills 分层架构**：BaseSkill 抽象基类统一接口，Skills（业务推理层）与 Tools（原子执行层）分离，v3_engine_router 通过统一调度分发
- **ReAct 循环**：cognitive_parser → v3_engine_router（工具执行）→ interpreter_generator（报告生成），token 级流式输出
- **多智能体架构**：BaseAgent + AGENT_REGISTRY 子图模式，各 Agent 目录/Prompt 隔离，支持多人并行开发
- **三层记忆架构**：L1 PostgresSaver checkpoint、L2 LangGraph store/LangMem 长期记忆、L3 现有 ChromaDB RAG（默认关闭，可配置启用）
- **多 LLM 支持**：DeepSeek V4 / OpenAI / Claude，`LLM_PROVIDER` 环境变量一键切换

## 快速开始

```bash
git clone https://github.com/Webr1ng/EnerGraph.git
cd EnerGraph
conda create -n energraph python=3.11 -y
conda activate energraph
pip install -r requirements.txt
```

配置环境变量：

```bash
cp .env.example .env
# 编辑 .env，至少填入：
# LLM_PROVIDER=deepseek
# DEEPSEEK_API_KEY=your_key
```

初始化 HVAC 知识库（首次运行，约 2-5 分钟）：

```bash
python -m src.pipelines.rag_ingest
```

可选：启动本地记忆数据库（PostgreSQL + pgvector）：

```bash
docker compose up -d
# .env 中设置 MEMORY_ENABLED=true 后，L1 checkpoint 将使用该 PostgreSQL
```

本地人工测试 L2 记忆时，可临时启用 demo 文件落盘（仅用于演示，不替代 PostgresStore）：

```bash
MEMORY_ENABLED=true MEMORY_DEMO_FILE_STORE_ENABLED=true streamlit run src/frontend/app.py --server.headless true
# demo 记忆文件：data/long_term_memory_demo/memories.json
```

启动演示前端：

```bash
streamlit run src/frontend/app.py --server.headless true
```

启动 API 服务（Phase 2 完成后）：

```bash
uvicorn src.services.api:app --reload
```

## 项目结构

```
EnerGraph/
├── CLAUDE.md                      # AI 协作规范（Claude Code 每次 session 自动加载）
├── AGENTS.md                      # OpenAI Codex CLI 入口指令（引用 CLAUDE.md）
├── AI_CONTEXT.md                  # 项目单点真相（开发前必读）
├── CHANGELOG.md                   # 完整变更历史记录
├── PRD.md                         # 产品需求文档（用户场景 + 功能定义）
├── MCP_INTERFACE_SPEC.md          # MCP 接口契约（9 个算法模型接口规范）
├── TEAM_COLLABORATION_GUIDE.md    # 团队协作开发指南（新同事必读）
├── docker-compose.yml             # 本地记忆模块 PostgreSQL + pgvector
├── config/
│   ├── agent_config.yaml          # 默认配置（.env 优先覆盖）
│   └── routes.yaml                # 前端路由注册表（24 可访问 + 10 受限）
├── docs/                          # 各阶段开发规划 + 项目文档
│   ├── plan_phase{2-7}_*.md       # 各 Phase 开发计划
│   ├── frontend_integration_guide.md  # 前端对接指南（Vue.js + TypeScript + SSE）
│   ├── TEAM_COLLABORATION_GUIDE.md    # 团队协作开发规范
│   └── REPORT_2026_06.md              # 管理层汇报文档
├── src/
│   ├── config/
│   │   ├── settings.py            # 统一配置加载（LLM_PROVIDER 切换）
│   │   └── prompts/               # System Prompt 按 Agent 拆分管理
│   │       ├── _shared.yaml       # 共享片段（回答原则/跳转规则）
│   │       ├── main_graph.yaml    # 主图节点 Prompt
│   │       ├── hvac_expert.yaml   # HVAC Agent 专属
│   │       ├── ui_router.yaml     # UI Router Agent 专属
│   │       └── powerai.yaml       # PowerAI Agent 专属
│   ├── schemas/
│   │   ├── v3_engine.py           # Pydantic 模型（ConstraintMatrix / IntentItem 等）
│   │   ├── action_agent.py        # PageContext / UIAction / COPData 等
│   │   └── memory.py              # MemoryQuery / MemoryItem / MemorySearchResult
│   ├── skills/                    # 业务技能层（Prompt + SOP + Tools 编排）
│   │   ├── base_skill.py          # BaseSkill 抽象基类（execute/生命周期钩子）
│   │   ├── hvac_expert_skill.py   # HVAC 专家问答（置信度判断/拒答/引用）
│   │   ├── energy_dispatch_skill.py   # 能源调度分析
│   │   ├── ui_router_skill.py     # 页面跳转控制（RouteRegistry 路由匹配）
│   │   └── v3_interpreter_skill.py    # 数据解读报告
│   ├── tools/                     # 原子执行层（确定性函数，不含 Prompt）
│   │   ├── query_hvac_knowledge.py    # HVAC RAG 检索（ChromaDB）
│   │   ├── parse_intent.py        # 意图解析 → ConstraintMatrix
│   │   ├── navigate_to_page.py    # 页面跳转 → UIAction
│   │   ├── memory_ops.py          # search_memory / save_memory 长期记忆工具
│   │   └── java_backend.py        # 福加运营数据工具（11 个真实 REST API）
│   ├── memory/
│   │   └── store.py               # L2 长期记忆 store 封装（namespace + TTL）
│   ├── utils/
│   │   └── fuca_token_refresher.py    # 福加 Token 自动刷新（RSA 加密登录）
│   ├── graph/                     # LangGraph 状态机
│   │   ├── state.py               # AgentState（TypedDict + Annotated）
│   │   ├── nodes.py               # 三个节点函数（含 Skill 调度分发）
│   │   ├── edges.py               # 条件路由
│   │   ├── builder.py             # graph 全局单例
│   │   └── agents/                # 多智能体 Subgraph 模块
│   │       ├── base_agent.py      # BaseAgent 抽象基类
│   │       ├── hvac_expert/       # HVAC 专家 Agent 子图
│   │       ├── ui_router/         # UI Router Agent 子图
│   │       └── powerai/           # PowerAI 储能调度 Agent 子图（骨架）
│   ├── services/
│   │   └── api.py                 # FastAPI SSE（/invoke + /stream）
│   ├── pipelines/
│   │   └── rag_ingest.py          # HVAC 语料入库（bge-small-zh-v1.5）
│   ├── frontend/
│   │   └── app.py                 # Streamlit 演示前端
│   └── tests/                     # 测试套件（66 tests）
│       ├── test_action_agent.py       # /stream 集成测试（9 tests）
│       ├── test_base_skill.py         # BaseSkill 契约测试（15 tests）
│       ├── test_hvac_quality.py       # RAG 质量测试（19 tests）
│       ├── test_multi_intent.py       # 多意图识别测试（16 tests）
│       ├── test_ui_router_skill.py    # 路由匹配测试（4 tests）
│       └── test_{agent_flow,customer_scenarios,fuca_api,navigation}.py
├── data/hvac_knowledge/           # ChromaDB 向量库（rag_ingest 后生成）
└── run.py                         # API 服务启动脚本
```

## 技术栈

| 类别 | 技术 |
|------|------|
| 核心框架 | LangGraph 1.2，ReAct 状态图 |
| LLM | DeepSeek V4 / OpenAI / Claude（`LLM_PROVIDER` 切换） |
| Embedding | BAAI/bge-small-zh-v1.5（SentenceTransformers，中文优化，本地模型） |
| 向量库 | ChromaDB 本地持久化，5605 条 HVAC 语料 |
| 记忆 | LangGraph checkpoint + LangGraph store/LangMem 0.0.30，PostgreSQL + pgvector（`psycopg[binary,pool]`） |
| API 层 | FastAPI + SSE 流式（Phase 2） |
| 前端对接 | Vue3 + Vite + TypeScript（福加监控平台） |
| 演示前端 | Streamlit 1.39 |
| 可观测性 | LangSmith（`LANGCHAIN_TRACING_V2=true`） |
| Python | 3.11 |

## 开发阶段

| 阶段 | 内容 | 状态 |
|------|------|------|
| Phase 1 | ReAct 循环 + HVAC RAG + DeepSeek V4 + 流式前端 | ✅ 完成 |
| Phase 2 | Action Agent：FastAPI SSE + UIAction 跳转信号 + Java 后端工具 | ✅ 完成 |
| Phase 3 | RAG 质量优化（置信度阈值 + MMR 去重 + 拒答 + 引用来源） | ✅ 完成 |
| Phase 4 | 福加真实 API 对接（11 个监控数据工具 + Token 自动刷新） | ✅ 完成 |
| Phase 5 | 语音助手（Whisper STT + TTS） | 待开始 |
| Phase 6 | 数据可视化 + 报表导出（表格/图表/CSV 下载） | 待开始 |
| Phase 7 | 多意图识别与拆分执行（IntentItem + 分段报告 + SSE） | ✅ 完成 |
| 架构重构 | 多智能体 Subgraph 架构（BaseAgent + AGENT_REGISTRY + Prompt 隔离） | ✅ 完成 |
| 记忆模块 | L1 checkpoint + L2 长期记忆 Tool + namespace/TTL 隔离 | 进行中 |
| API 交付 | CORS + 鉴权 + 启动脚本 + 前端对接文档（Vue.js） | ✅ 完成 |

## 团队协作

新同事加入请按以下顺序阅读：

1. **[TEAM_COLLABORATION_GUIDE.md](TEAM_COLLABORATION_GUIDE.md)** — 项目架构概览 + Git 工作流 + 开发规范
2. **[AI_CONTEXT.md](AI_CONTEXT.md)** — 项目技术细节单点真相
3. **[CLAUDE.md](CLAUDE.md)** — AI 编程助手协作准则（Claude Code / Codex 自动加载）
4. **[PRD.md](PRD.md)** — 产品需求文档（做什么 / 不做什么）

## 开发规范

详见 [CLAUDE.md](CLAUDE.md)。核心原则：

- Agent **禁止**手写能源计算，所有数据通过 Tools 获取
- 算法模型通过 MCP 协议调用（接口契约已定义，见 `MCP_INTERFACE_SPEC.md`）
- Skills 封装业务推理（Prompt + SOP），Tools 封装原子执行
- `AgentState` 用 `TypedDict + Annotated`，Tool I/O 用 Pydantic BaseModel
- Prompt 集中管理至 `src/config/prompts/*.yaml`（按 Agent 拆分），禁止硬编码
- 每个 `.py` 文件必须有模块 docstring（层 / 依赖 / 对接引擎）
- 提交格式：`[模块] 动词短语`，禁止 `git add .`

## 许可

内部项目，未公开授权。© 2026 南京福加智能科技有限公司
