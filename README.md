# EnerGraph — 青山大模型 V3.0 决策层

基于 LangGraph 的企业级能源管理 AI Agent，定位为青山大模型 V3.0 五层架构的**第 3 层决策层 + 第 4 层自演化引擎层演进底座**。Agent 负责意图理解、工具调度、决策解释与记忆编排，自身不做能源数值计算。

当前能力覆盖 HVAC 专家问答、用户文档上传并自动进入 RAG 知识库、福加运营数据与预测查询、页面跳转控制、自动图表 + 表格 + CSV 数据导出、多意图拆分、多智能体 Subgraph 架构与可配置记忆能力，并通过 FastAPI SSE 接口向前端下发 `text` / `action` / `data_card` 等事件。

## 功能

- **HVAC 专家问答**：5605 条暖通空调专业语料（规范查询、能效计算、故障诊断、节能优化），RAG 检索驱动，低置信度自动拒答，引用来源标注
- **用户文档知识库 RAG**：在 Streamlit 知识库管理区或 FastAPI `/knowledge/documents` 上传 `.doc` / `.docx` / `.txt` / `.json` / 文字型 `.pdf`，自动解析、切块并写入独立 `uploaded_documents` collection；支持状态查看、失败重解析、重复文件复用和删除同步清理 chunks，回答显示文件名/页码/章节来源
- **RAG 质量优化**：distance 阈值过滤 + 余弦相似度 MMR 去重（0.98 阈值）+ source_snippets 引用来源
- **多意图识别**：单输入多意图自动拆分，cognitive_parser 并行/串行调度，interpreter 分段报告输出
- **Action Agent**：理解自然语言意图 → 调用 Java 后端监控 API → 流式返回文字总结 + 页面跳转信号
- **真实数据与预测查询**：通过福加 REST API 查询能耗、COP、报警、光伏等运营数据；支持光伏预测、冷负荷预测、电负荷预测的单日查询与多日范围查询，查询后跳转对应分析页
- **数据导出（Phase 6）**：支持能耗、历史报警、光伏预测、冷负荷预测、电负荷预测、COP 能效日历等数据导出；`export_data_table` 基于同一批真实 rows 生成轻量 `ChartSpec`、表格和 CSV，并通过 SSE `data_card` 统一下发
- **自动图表**：按数据结构与用户意图生成 line / bar / pie / donut 图表；显式图表类型优先，自动推荐限制同单位序列数量，无法安全推荐时降级为表格 + CSV，不生成后端图片文件
- **报表下载跳转**：运维报表 / 用能报表 / 报表管理类需求直接跳转 `/report-center/manage`，不调用数据查询工具、不代答报表数值
- **Skills 分层架构**：BaseSkill 抽象基类统一接口，Skills（业务推理层）与 Tools（原子执行层）分离，v3_engine_router 通过统一调度分发；Skill 描述由类属性单点派生，避免注册信息漂移
- **ReAct 循环**：cognitive_parser → v3_engine_router（工具执行）→ interpreter_generator（报告生成），token 级流式输出
- **多轮状态隔离**：Tool 迭代额度仅统计当前用户轮次，新一轮自动清理 HVAC、意图计划和报告等临时状态，避免历史 checkpoint 导致错误路由
- **多智能体架构**：BaseAgent + AGENT_REGISTRY 子图模式，各 Agent 目录/Prompt 隔离，支持多人并行开发
- **三层记忆架构**：L1 checkpoint、L2 LangGraph store/LangMem 长期记忆、L3 现有 ChromaDB RAG（默认关闭，可配置启用；支持 LLM 结构化自动抽取、namespace/TTL 隔离、本地 demo 文件落盘）
- **PowerAI 过渡期边界**：MCP Server 正式接入前，光伏/负荷/储能调度等预测相关数据只使用已注册的福加后端数据工具；无工具时明确说明暂缺接口，不编造预测曲线、收益测算或充放电策略
- **多 LLM 支持**：DeepSeek V4 / OpenAI / Claude，`LLM_PROVIDER` 环境变量一键切换

## 最近更新（截至 2026-07-13）

- **用户文档知识库 RAG 核心完成**：支持五种文件格式的上传、解析、切块、向量入库、来源引用、低置信度拒答、删除和重解析；新增 Streamlit 管理区、FastAPI 管理接口及前端对接说明。扫描型 PDF 的 OCR 留待后续版本

- **Phase 6 完成**：DataCard 已支持自动图表、表格和 CSV；图表使用轻量 JSON 协议，支持 line / bar / pie / donut、外圈构成标签、排名柱状图和安全降级，不生成 PNG/JPG/SVG/Base64
- **预测能力扩展**：接入光伏、冷负荷、电负荷三类福加预测接口及范围查询，可完成单日分析、多日导出与对应页面跳转
- **记忆链路增强**：L1 PostgresSaver 与 L2 PostgresStore 已通过本机 PostgreSQL 建表、重连读取和确定性 upsert 验收；收紧长期记忆抽取、查询和回答偏好的质量闸门，待服务器环境最终验收
- **多轮路由修复**：历史消息不再消耗当前轮 Tool 回环额度，新轮次清理临时业务状态，修复第三轮以后误入 HVAC 报告的问题
- **输出边界收敛**：禁止编造数值、CSV、正文跳转链接和未注册 MCP 结果；图表、表格、CSV 必须共享工具返回的真实 rows

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

本地人工测试 L2 记忆时，可临时启用 demo 文件落盘（仅用于演示，不替代 PostgresStore）：

```bash
MEMORY_ENABLED=true MEMORY_AUTO_EXTRACT_ENABLED=true MEMORY_DEMO_FILE_STORE_ENABLED=true streamlit run src/frontend/app.py --server.headless true
# demo 记忆文件：data/long_term_memory_demo/memories.json
```

生产或本地 PostgreSQL 联调使用真实 L1/L2 持久化：

```bash
MEMORY_ENABLED=true \
MEMORY_USE_POSTGRES_STORE=true \
MEMORY_DEMO_FILE_STORE_ENABLED=false \
MEMORY_POSTGRES_DSN='postgresql://user:password@host:5432/energraph' \
python run.py
```

首次初始化需设置 `MEMORY_POSTGRES_SETUP_ENABLED=true`；建表完成后生产应用可改为 `false` 并使用最小权限账号。多用户部署时 `/invoke`、`/stream` 请求应传稳定 `user_id`，避免不同用户共享 `default_user` 偏好。完整部署、备份与恢复流程见 `docs/postgres_memory_operations.md`。

启动演示前端：

```bash
streamlit run src/frontend/app.py --server.headless true
```

知识库上传测试：启动 Streamlit 后，在左侧“知识库管理（上传文件 RAG）”选择支持的文件，点击“上传并自动入库”。状态变为 `ready` 后，在聊天框中提问，例如：

```text
根据我上传的运维手册，冷水机组的月度维护要求是什么？请注明文件和页码。
```

上传文档会持久化到 `data/knowledge_uploads/`，向量写入 `data/hvac_knowledge/` 下的 `uploaded_documents` collection；重启服务后仍可检索。删除请使用 Streamlit 的“删除”按钮或 `DELETE /knowledge/documents/{document_id}`，不要只手动删除原文件。

启动 API 服务：

```bash
python run.py
# 或：uvicorn src.services.api:app --reload
```

常用接口：

- `POST /invoke`：同步调用，返回 `report` / `actions` / `data_cards`
- `POST /stream`：SSE 流式调用，事件含 `thinking` / `tool_call` / `tool_result` / `rag_sources` / `text` / `action` / `data_card` / `done`
- `GET /export/{task_id}`：下载 `export_data_table` 生成的 CSV（`task_id` 为 uuid hex）
- `POST /knowledge/documents`：multipart 上传文档并自动入库
- `GET /knowledge/documents`：查看文档列表和处理状态
- `GET /knowledge/documents/{document_id}`：查看单个文档详情
- `POST /knowledge/documents/{document_id}/reprocess`：重新解析原文件
- `DELETE /knowledge/documents/{document_id}`：删除原文件、登记信息和对应 Chroma chunks

数据导出文件落盘在 `data/exports/{task_id}.csv`，`data/` 目录已被忽略，不提交导出文件。

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
│   │   ├── data_card.py           # ColumnDef / TableData / DownloadInfo / DataCard
│   │   ├── document_knowledge.py  # 文档登记、检索结果与来源模型
│   │   └── memory.py              # MemoryQuery / MemoryItem / MemorySearchResult / MemoryWriteResult
│   ├── skills/                    # 业务技能层（Prompt + SOP + Tools 编排）
│   │   ├── base_skill.py          # BaseSkill 抽象基类（execute/生命周期钩子）
│   │   ├── hvac_expert_skill.py   # HVAC 专家问答（置信度判断/拒答/引用）
│   │   ├── document_knowledge_skill.py # 上传文档 RAG 拒答与来源引用
│   │   ├── energy_dispatch_skill.py   # 能源调度分析
│   │   ├── ui_router_skill.py     # 页面跳转 + DataCard 下发
│   │   └── v3_interpreter_skill.py    # 数据解读报告
│   ├── tools/                     # 原子执行层（确定性函数，不含 Prompt）
│   │   ├── query_hvac_knowledge.py    # HVAC RAG 检索（ChromaDB）
│   │   ├── query_uploaded_documents.py # 上传文档 RAG 检索（独立 collection）
│   │   ├── parse_intent.py        # 意图解析 → ConstraintMatrix
│   │   ├── navigate_to_page.py    # 页面跳转 → UIAction
│   │   ├── export_data.py         # 自动图表 + 表格 + CSV → DataCard
│   │   ├── memory_ops.py          # search_memory / search_relevant_memory / save_memory
│   │   └── java_backend.py        # 福加运营/预测数据工具（20 个，含范围查询）
│   ├── memory/
│   │   ├── extractor.py           # LLM 结构化长期记忆抽取
│   │   └── store.py               # L2 长期记忆 store 封装（namespace + TTL + fallback）
│   ├── utils/
│   │   ├── chart_recommender.py   # 按真实 rows 自动推荐轻量图表
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
│   │   ├── api.py                 # FastAPI SSE 与文档知识库管理 API
│   │   └── document_knowledge.py  # 文档保存、解析、切块、入库、状态与删除
│   ├── pipelines/
│   │   └── rag_ingest.py          # HVAC 语料入库（bge-small-zh-v1.5）
│   ├── frontend/
│   │   └── app.py                 # Streamlit 演示前端
│   └── tests/                     # 测试套件（文档 RAG、HVAC、SSE、记忆与工具回归）
│       ├── test_action_agent.py       # /stream 集成测试（9 tests）
│       ├── test_base_skill.py         # BaseSkill 契约测试（15 tests）
│       ├── test_hvac_quality.py       # RAG 质量测试（19 tests）
│       ├── test_multi_intent.py       # 多意图识别测试（16 tests）
│       ├── test_ui_router_skill.py    # 路由匹配测试（4 tests）
│       ├── test_data_export.py        # Phase 6 图表、导出与 DataCard 契约测试
│       ├── test_memory_*.py           # 记忆 store/tool/隔离/抽取/聚合检索测试
│       └── test_{agent_flow,customer_scenarios,fuca_api,navigation}.py
├── data/hvac_knowledge/           # ChromaDB 向量库（含 hvac_qa 与 uploaded_documents collection）
├── data/knowledge_uploads/        # 上传原文件与文档登记库（本地运行时生成）
└── run.py                         # API 服务启动脚本
```

## 技术栈

| 类别 | 技术 |
|------|------|
| 核心框架 | LangGraph 1.2，ReAct 状态图 |
| LLM | DeepSeek V4 / OpenAI / Claude（`LLM_PROVIDER` 切换） |
| Embedding | BAAI/bge-small-zh-v1.5（SentenceTransformers，中文优化，本地模型；HVAC 与上传文档 RAG 复用） |
| 向量库 | ChromaDB 本地持久化，5605 条 HVAC 语料 |
| 文档解析 | python-docx / pypdf；旧版 `.doc` 依赖系统 antiword；扫描 PDF OCR 后续支持 |
| 记忆 | LangGraph checkpoint + LangGraph store/LangMem 0.0.30，PostgreSQL + pgvector（`psycopg[binary,pool]`）；本地联调可用 demo 文件落盘 |
| API 层 | FastAPI + SSE 流式（`/invoke`、`/stream`、`/export/{task_id}`） |
| 数据可视化与导出 | 轻量 `ChartSpec` JSON + 标准库 `csv`（utf-8-sig BOM），统一 `DataCard` 前端协议 |
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
| Phase 4 | 福加真实 API 对接（20 个已注册运营/预测/范围查询工具 + Token 自动刷新）；算法模型 MCP 接口契约已定义，待算法团队 Server 接入 | 大部分完成 |
| Phase 5 | 语音助手（Whisper STT + TTS） | ⏸️ 延后 |
| Phase 6 | 数据导出（自动图表 + 表格 + CSV 下载，统一 DataCard 协议） | ✅ 完成 |
| Phase 7 | 多意图识别与拆分执行（IntentItem + 分段报告 + SSE） | ✅ 完成 |
| 架构重构 | 多智能体 Subgraph 架构（BaseAgent + AGENT_REGISTRY + Prompt 隔离） | ✅ 完成 |
| 记忆模块 | L1 checkpoint + L2 长期记忆 Tool + namespace/TTL 隔离 + 自动抽取质量闸门 | 🔧 本机 PostgreSQL 验收通过，待服务器验收 |
| API 交付 | CORS + 鉴权 + 启动脚本 + 前端对接文档（Vue.js） | ✅ 完成 |
| 用户文档 RAG | 文件上传、解析、自动入库、来源引用、状态/重解析/删除 | ✅ 核心代码完成，待服务器内网验收 |

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
- MCP Server 正式接入前，PowerAI 只使用已注册后端数据工具；无工具时明确说明接口暂缺
- Skills 封装业务推理（Prompt + SOP），Tools 封装原子执行
- `AgentState` 用 `TypedDict + Annotated`，Tool I/O 用 Pydantic BaseModel
- Prompt 集中管理至 `src/config/prompts/*.yaml`（按 Agent 拆分），禁止硬编码
- 每个 `.py` 文件必须有模块 docstring（层 / 依赖 / 对接引擎）
- 提交格式：`[模块] 动词短语`，禁止 `git add .`

## 许可

内部项目，未公开授权。© 2026 南京福加智能科技有限公司
