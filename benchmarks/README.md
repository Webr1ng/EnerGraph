# EnerGraph Eval v0.1

本目录承载 EnerGraph 的统一离线评测与发布验收资产。v0.1 只评估 Agent 的意图理解、路由、工具编排、证据使用、记忆、回答和前端协议，不评估算法模型自身的预测或优化精度，也不在评测代码中实现能源计算。

## 1. 分层与测试入口

| 层级 | 范围 | 默认依赖 | 入口 | 当前状态 |
|---|---|---|---|---|
| L1 | 函数、Schema、Store、协议 | Mock / InMemory | 见下方 Fast 基线命令 | 已有；默认套件合计 389 passed / 6 skipped |
| L2 | P0 确定性回归门禁 | Mock LLM / Mock Tool | `src/tests/test_*_regression.py` | T9 完成，五类 62 cases |
| L3 | 版本化 MiniBench | 固定或真实 LLM、Mock Tool | `python -m benchmarks.runners.run_all` | T3 公共闭环完成，T4 起建设业务集 |
| L4 | 真实环境发布验收 | PostgreSQL、LLM、API/MCP | 独立验收命令与 manifest | E4 建设 |

Fast 模式不得访问网络或真实 PostgreSQL。Standard 可使用固定模型或真实模型，但 Tool 响应固定。Production 缺少真实依赖时必须快速失败，不得回退后伪装成生产结果。

当前 Fast 基线命令必须显式覆盖本地 `.env`，防止开发机的 PostgreSQL 或现场测试配置污染结果：

```bash
MEMORY_ENABLED=false \
MEMORY_USE_POSTGRES_STORE=false \
MEMORY_DEMO_FILE_STORE_ENABLED=false \
RUN_LIVE_AGENT_TESTS=0 \
RUN_FUCA_API_TESTS=0 \
conda run -n energraph pytest src/tests/ -q
```

现场测试默认关闭：`test_agent_flow.py` 与 `test_customer_scenarios.py` 需 `RUN_LIVE_AGENT_TESTS=1`，`test_fuca_api.py` 需 `RUN_FUCA_API_TESTS=1`。`test_navigation.py` 是手工检查脚本，不由 pytest 收集。

## 2. v0.1 范围冻结

### 2.1 纳入范围

- Memory：抽取准入、写入、upsert、检索、删除、TTL、namespace 隔离和最终使用；
- Routing：单/多意图、Agent/Skill 路由、歧义与上下文；
- Tool Call：工具名、次数、顺序、参数、禁止调用和错误路径；
- Faithfulness：数值、单位、日期、站点、来源、CSV/DataCard 与 Tool 证据一致；
- Safety：权限隔离、敏感信息、提示注入、安全约束和降级；
- RAG、最终回答、多意图完整性、SSE、UIAction、DataCard、性能和故障恢复。

### 2.2 不纳入范围

- 算法模型预测/优化精度和能源公式；
- 默认 CI 中的真实 LLM、福加 API、MCP 或 PostgreSQL；
- v0.1 强制 LLM Judge、在线 A/B 或大规模长对话；
- 将 LangSmith 或任一模型供应商作为唯一后端。

## 3. 当前能力清单（2026-07-07）

| 类型 | 数量 | 清单/说明 |
|---|---:|---|
| Tool registry | 27 | 20 个福加运营/预测查询，HVAC RAG、导航、导出、3 个记忆工具及内部 `parse_business_intent` |
| LLM Tool schemas | 26 | `parse_business_intent` 不绑定给主 Agent；其余注册 Tool 均有 schema |
| Skills | 4 | `hvac_expert`、`energy_dispatch`、`ui_router`、`v3_interpreter` |
| Agents | 3 | `hvac_expert`、`ui_router`、`powerai` |
| Routes | 36 | 可访问 26，受限 10 |
| pytest files | 27 | 318 cases；另有 1 个手工导航脚本 |

能力清单的单点真相分别为 `src/tools/__init__.py`、`src/skills/__init__.py`、`src/graph/agents/__init__.py`、`config/routes.yaml` 和 `src/schemas/`。E1 起应从这些注册表自动导出，不在数据集中复制维护。

## 4. 现有测试盘点与差距

| 领域 | 现有覆盖 | 层级判定 | 主要缺口 |
|---|---|---|---|
| Memory | 配置、抽取闸门、InMemory/demo/Postgres facade、隔离、TTL、相关检索、Tool | L1 | 版本化数据集、Write P/R、Recall@5/MRR、泄漏/过期硬门禁、真实跨进程验收；默认 pytest 会继承本地 `.env` 的 PostgreSQL 开关，Fast 入口需在 E1 隔离环境配置 |
| Routing / Multi-intent | Mock LLM 路由状态、Skill 注册、循环上限、多意图计划 | L1 | 成规模改写/歧义集、Agent accuracy、Macro F1、路由漂移 |
| Tool / Forecast / Export | 参数、错误、重试、范围查询、导航、CSV/DataCard | L1 | required/forbidden/order 通用评分、错误站点与越权 gate |
| RAG | Mock ChromaDB 阈值、去重、引用与拒答 | L1 | 固定语料快照、Recall@k、MRR、nDCG、Citation Precision |
| SSE / UI | action、intent plan、data_card、thread/page context | L1 | 全事件 schema/顺序、唯一 done、断流与最终文本去重 |
| Faithfulness | Prompt 红线和部分 rows/CSV 契约 | 零散 L1 | 回答 claim 抽取、数值/单位/站点证据比对、无答案 gate |
| Safety | 导出路径穿越、记忆隔离及配置脱敏 | 零散 L1 | 权限矩阵、prompt injection、日志密钥扫描、越权 Tool gate |
| Live services | 6 个案例由环境变量显式开启 | 外部集成冒烟 | manifest、独立 namespace、性能/恢复与发布判定 |

现有测试都不属于真实模型质量评测；即使测试内部使用 PostgresStore fake 或 Mock LLM，也仍按 L1 确定性测试归类。

## 5. 产品红线追踪矩阵

| 产品红线 | 指标 / 硬门禁 | 测试层级 | 责任模块 | 计划 Task |
|---|---|---|---|---|
| 不自行计算或编造能源/运营数据 | 无依据能源数值生成率 = 0；Numeric Faithfulness | L2/L3/L4 | Faithfulness、Tool | T6/T7/T9/T14 |
| 数据必须来自正确 Tool 和站点 | 错误站点数据使用率 = 0；Tool F1/参数准确率 | L2/L3/L4 | Routing、Tool | T5/T6/T9/T14 |
| RAG 低置信度不得猜答 | 无答案正确拒答率；Supported Claim Rate | L2/L3 | RAG、Answer | T7/T9/T10/T11 |
| 不在正文引导或伪造页面跳转 | 禁止话术命中率 = 0；route/schema 合法率 = 100% | L2/L3 | UI Contract | T9/T12 |
| 敏感数据不得泄露或越权读取 | 泄漏率、越权 Tool 调用率 = 0 | L2/L3/L4 | Memory、Safety | T4/T8/T9/T14 |
| Prompt 必须外部化 | 硬编码 Prompt 静态检查失败数 = 0 | L1/L2 | Config、Safety | T8/T9 |
| 记忆按 env/site/user/agent 隔离 | 跨域记忆泄漏率 = 0 | L2/L3/L4 | Memory | T4/T9/T14 |
| 过期/删除记忆不可使用，设备状态不可自动长期写入 | 过期/删除使用率、设备状态误写率 = 0 | L2/L3/L4 | Memory | T4/T9/T14 |
| SSE/DataCard 必须符合前端契约 | SSE 非法率、DataCard rows 不一致率 = 0 | L2/L3 | UI Contract、Faithfulness | T7/T9/T12 |
| 首 token < 2s，P99 < 2s（PRD 当前口径） | TTFT P99；端到端 P50/P95/P99 | L4 | Performance | T13 |

性能阈值需在真实部署基线后复核；当前仅冻结 PRD 口径，不宣称已达标。

## 6. 术语与标识规范

- Case ID：`<module>_<scenario>_<nnn>`，仅用小写字母、数字和下划线，例如 `memory_isolation_001`；发布后不可复用或改变语义。
- 数据集版本：目录使用 `v0_1`，用例字段使用 `0.1`；不兼容变更升次版本。
- 模块名固定为 `memory`、`routing`、`tool_call`、`faithfulness`、`safety`、`rag`、`multi_intent`、`answer`、`ui_contract`、`performance`。
- Gate：违反即整次运行失败的零容忍规则；Metric：允许按确认阈值或基线比较的质量指标。
- Fixture：脱敏、确定性的输入或外部依赖响应；不得包含生产会话原文、真实 Token、密码、DSN 或可识别设备 ID。
- 报告仅保存必要证据摘要；站点、用户、thread 和设备统一使用合成 ID。提交前扫描 `api_key`、`token`、`password`、`authorization`、`postgresql://` 等敏感模式。

## 7. 外部依赖与责任

| 未就绪/待确认项 | 当前处置 | 责任 |
|---|---|---|
| 本地真实 LLM 服务与固定模型版本 | 已接入 `qwen3.6-35b-a3b`（Qwen3.6-35B-A3B AWQ）；健康、直呼、Standard GraphAdapter 和完整 HVAC RAG Agent 链路均已通过 | 项目负责人 |
| 服务器 PostgreSQL 发布环境 | 本机已验收，服务器 L4 暂缓 | 项目负责人 / 运维待指定 |
| 福加 API 稳定测试环境与账号 | 默认测试禁用，仅显式现场验收 | 后端接口负责人待指定 |
| 算法模型 MCP Server | 尚未接入，不伪造 Production 结果 | 算法团队负责人待指定 |
| v0.1 阈值和 baseline 审批 | 首次基线后由项目负责人确认 | 项目负责人待指定 |

责任人未在现有项目文档中明确，因此 E0 如实标为“待指定”，不代替负责人做组织授权假设。

## 8. E0 验收结论

PRD 六项禁止行为和记忆/前端协议扩展红线均已映射到指标、层级、模块和后续 Task；现有自动测试、现场测试与手工脚本已分开归类。E0/T0 范围冻结已完成，其后 E1/T1 统一契约也已完成，当前进入 E1/T2。

## 9. E1/T1 契约入口

- 共用模型：`benchmarks/shared/result_models.py`；Schema 版本固定为 `0.1`。
- JSONL 加载、唯一 ID、脱敏和确定性序列化：`benchmarks/shared/case_loader.py`。
- 最小合法、多轮合法和未知版本非法样例：`benchmarks/datasets/_examples/`。
- 回归入口：`pytest -q src/tests/test_eval_contracts.py`。

T1 验收已完成：合法样例可加载，重复 ID、未知版本、非法 ID 和冲突工具集合会明确失败；Bearer、DSN 与凭据字段会脱敏，`input_tokens/output_tokens` 等非凭据计数保留。真实模型 `qwen3.6-35b-a3b` 的 EnerGraph 输出可通过 `EvalResult` 建模且硬门禁未触发。下一阶段为 E1/T2 Adapter、Fixture 与运行配置边界。

## 10. E1/T2 配置与 Adapter 入口

- 配置：`benchmarks/configs/{fast,standard,production,thresholds}.yaml`。
- Adapter：Graph、API、Memory、Tool、RAG 共用统一响应、namespace、timeout 和 retry 生命周期。
- Fixture：`benchmarks/fixtures/scripted_responses.json`，仅保存固定脱敏响应。
- 回归入口：`pytest -q src/tests/test_eval_adapters.py`。

T2 验收已完成：同一案例可通过 Fast/Standard Adapter 契约；Fast 网络调用被代码阻断；Production 缺真实依赖会在启动前失败；案例 namespace 在成功或异常后均清理；timeout 与有限 retry 均有确定性测试。真实 Graph 执行器可提取回答、意图、Tool calls 和 token 用量。HVAC RAG 已改为 `local_files_only` 加载并进程内缓存 embedding function：未设置任何全局离线环境变量时，真实检索 5.8 秒返回 3 条结果，完整 `qwen3.6-35b-a3b` HVAC Agent 链路 15.14 秒完成且 `error=None`。

## 11. E1/T3 Runner、Scorer 与报告入口

最小 Fast 闭环：

```bash
python -m benchmarks.runners.run_all \
  --dataset benchmarks/datasets/_examples/minimal_valid.jsonl \
  --config benchmarks/configs/fast.yaml \
  --output-dir benchmarks/reports/t3_fast_smoke \
  --baseline benchmarks/baselines/v0_1.json \
  --run-id t3-fast-smoke
```

支持 `--case-id`、`--tag`、`--category` 筛选，`--resume` 断点续跑，`--baseline` 比较新增失败、已修复失败和指标变化。报告固定生成 `results.json`、`summary.md`、`run_manifest.json`，运行产物由 `.gitignore` 排除；版本基线放 `benchmarks/baselines/`。`benchmarks/reports/README.md` 说明本地历史报告判读规则：旧 `FAIL` 仅代表当次运行，MR/发布以最新 run_id、CHANGELOG/AI_CONTEXT 和最终脱敏报告为准。

T3 验收已完成：Fast 正例生成报告且退出码 0；故意命中禁止回答文本时硬门禁失败且退出码 1；失败案例不阻断后续案例；宏/微聚合、Scorer 重名检查、脱敏 Manifest、续跑与 baseline diff 均有回归测试。T3 只提供公共框架和最小通用 Scorer，Memory 等业务指标从 T4 起按计划实现。

## 12. E2/T4 Memory MiniBench

Memory v0.1 使用 10 个基础场景 × 10 组 `env/site/agent/user/thread` 变体生成 100 条记录，覆盖用户偏好、站点事实、安全约束、设备状态拒写、可重新查询数据拒写、同 namespace 检索、站点/Agent 隔离、TTL 过滤、稳定 key upsert 和无答案。

```bash
# InMemory Fast
python -m benchmarks.runners.run_memory \
  --config benchmarks/configs/fast.yaml \
  --output-dir benchmarks/reports/t4_memory_fast \
  --baseline benchmarks/baselines/memory_v0_1.json

# PostgreSQL 独立发布集（需要 MEMORY_POSTGRES_DSN）
python -m benchmarks.runners.run_memory \
  --config benchmarks/configs/memory_postgres.yaml \
  --output-dir benchmarks/reports/t4_memory_postgres \
  --baseline benchmarks/baselines/memory_v0_1.json
```

T4 验收结果：InMemory 与本机 PostgreSQL 各 100 cases，Write P/R/F1、类型/Key准确率、Recall@5、Precision@5、MRR、Update Accuracy 均为 1.0，硬门禁 0。故意构造的跨 namespace 泄漏、过期使用、删除后使用、安全约束违反和设备状态无 TTL 写入均能触发对应 gate。PostgreSQL 使用 `energraph_eval_memory/eval` 独立前缀并逐案例清理。此前产品代码无公开单条 delete API，导致“删除后真实 Store 不可读”只能评分不能走产品路径；现已补齐 `MemoryStore.delete()` 与管理端 `delete_memory` 工具，并用 InMemory/PostgresStore fake 路径回归覆盖。真实服务器 PostgreSQL 的单条删除验收仍随 T14 Production/发布环境独立复验，不伪造通过。

Fast runner 会在启动时按 `fast.yaml` 强制关闭 `MEMORY_USE_POSTGRES_STORE`、`MEMORY_ENABLED` 和 demo 文件落盘，避免开发机 `.env` 中的 PostgreSQL 开关污染离线门禁。PostgreSQL 发布集只在 `memory_postgres.yaml` 且 `MEMORY_POSTGRES_DSN` 显式存在时启用。

## 13. E2/T5 Routing MiniBench

Routing v0.1 使用 16 个基础场景 × 5 种同义、口语和近邻表述生成 80 records，覆盖 HVAC、运营/报警查询、导航、导出、预测、PowerAI、记忆操作、闲聊、域外拒答和歧义澄清。

```bash
python -m benchmarks.runners.run_routing \
  --config benchmarks/configs/fast.yaml \
  --output-dir benchmarks/reports/t5_routing_fast \
  --baseline benchmarks/baselines/routing_v0_1.json
```

Fast 结果为 80/80，Intent Accuracy、Intent Macro-F1、Top-3 Accuracy、Agent Accuracy、Skill Accuracy 均为 1.0。Scorer 可分别定位 Intent/Agent/Skill 漂移；真实 Graph Adapter 从 Tool calls 推导业务路由，并从最终回答区分无 Tool 的记忆查询、域外拒答、澄清和普通闲聊。

Standard 已完成：故障时 vLLM `/health` 正常但生成无响应；服务实例随后重启，恢复后原生 API、LangChain 非流式与流式调用均正常。排查同时修复两项评测观测问题：Runner 先加载 `.env` 再做 required-env 预检；辅助 `navigate_to_page/search_relevant_memory` 不再污染主意图，并补无 Tool 澄清识别。`qwen3.6-35b-a3b` 6 条代表性子集统一重评分为 6/6，五项指标全 1.0。完整 80-record 真实模型运行仍留待每日 Standard 基线，本次 T5 功能验收通过。

## 14. E2/T6 Tool Call MiniBench

Tool Call v0.1 使用 16 个基础场景 × 5 种表述生成 80 records，覆盖能耗、报警、预测、COP、碳排、HVAC、导航、导出，以及缺站点、非法日期和空数据禁止导出。支持参数精确、类型、范围、枚举、日期与 dict 子集比较，并独立评分 Tool P/R/F1、参数、次数和顺序。

```bash
python -m benchmarks.runners.run_tools \
  --config benchmarks/configs/fast.yaml \
  --output-dir benchmarks/reports/t6_tools_fast \
  --baseline benchmarks/baselines/tool_call_v0_1.json
```

Fast 结果为 80/80，六项指标全 1.0，硬门禁 0；故意构造的越权 Tool、错误站点和 Tool error/空数据后假导出均能触发 gate。Standard 使用 `qwen3.6-35b-a3b` 完成能耗、COP、导航、HVAC、非法日期 5 条代表集。首次报告暴露评测契约仍沿用抽象 `site_demo`、旧导航 `keyword`，且未将数据查询后的合法 `navigate_to_page` 视为 optional；对齐注册站点 `FJJB000001`、真实 `route` 参数及 Tool 默认当天语义后，保存的原始结果重评分 5/5，六项全 1.0、gate 0。后续排查确认所谓“超过 120 秒”是 5 案例批次无逐案例输出造成的观测误判：120 秒是单案例预算，vLLM 指标中的 90 次请求均成功且最慢位于 30～40 秒区间。T6 功能验收完成，Runner 逐案例进度留待后续增强。

## 15. E2/T7 数据忠实度与拒答 MiniBench

Faithfulness v0.1 使用 10 个固定证据场景 × 5 种表述生成 50 records，覆盖精确数值、允许四舍五入、碳排、部分数据、空数据、Tool error、冲突、过期、RAG 低置信度和 DataCard rows 一致性。Scorer 独立计算 Supported Claim Rate、Numeric Faithfulness、Correct Abstention、DataCard Consistency，并对无依据能源数值、错误单位/站点、假 DataCard 和应拒未拒设置硬门禁。

```bash
python -m benchmarks.runners.run_faithfulness \
  --config benchmarks/configs/fast.yaml \
  --output-dir benchmarks/reports/t7_faithfulness_fast \
  --baseline benchmarks/baselines/faithfulness_v0_1.json
```

Fast 50/50，四项指标全 1.0、gate 0；故意构造的无依据数值、错误单位、错误站点、空数据编造和 DataCard rows 漂移均可触发对应门禁。Standard 使用外置回答规则和相同固定证据测试本地 `qwen3.6-35b-a3b`，5 条代表集覆盖精确值、格式化、部分数据、空数据和冲突拒答；保存输出按最终 Scorer 重评分 5/5，四项全 1.0、gate 0。全量隔离回归为 320 passed / 6 skipped。

## 16. E2/T8 安全、权限与提示注入 MiniBench

Security v0.1 使用 10 个攻击面 × 5 种表述生成 50 records，覆盖跨用户/站点读取、伪造 site_id、越权导出、system prompt 与凭据窃取、用户/RAG/Tool 三通道注入，以及覆盖安全约束诱导编造。测试只使用合成 canary，不包含真实密钥。Scorer 计算 Safe Response Rate、Secret Protection Rate、Authorization Accuracy、Injection Resistance，并对敏感值泄露、越权 Tool、跨 scope 访问、服从注入和不安全回答/编造设置硬门禁。

```bash
python -m benchmarks.runners.run_security \
  --config benchmarks/configs/fast.yaml \
  --output-dir benchmarks/reports/t8_security_fast \
  --baseline benchmarks/baselines/security_v0_1.json
```

Fast 50/50，四项指标全 1.0、gate 0；合成泄密、越权导出、跨站点读取、服从 RAG 注入和无证据编造负例均能触发相应 gate。Standard 使用外置安全规则测试本地 `qwen3.6-35b-a3b`：system prompt、API Key/DSN、用户注入、RAG 注入、Tool 注入五条代表集 5/5，四项全 1.0、gate 0，canary 无泄露。全量隔离回归为 327 passed / 6 skipped。

## 17. E2/T9 P0 离线回归门禁

T9 从五项完整 MiniBench 各保留每个基础场景的首个稳定变体，形成每个 PR 默认运行的 62 个 L2 case：Memory 10、Routing 16、Tool 16、Faithfulness 10、Security 10。每个 case 使用 pytest 参数 ID 暴露原始 case_id，失败时可直接定位红线；全部使用 Fast Fixture/InMemory，禁止网络、真实 LLM、外部密钥和 PostgreSQL。Memory 文件通过 autouse fixture 强制关闭 PostgreSQL/demo Store 并在每例前后 reset，开发机 `.env` 无法污染门禁。

```bash
pytest \
  src/tests/test_memory_regression.py \
  src/tests/test_routing_regression.py \
  src/tests/test_tool_regression.py \
  src/tests/test_faithfulness_regression.py \
  src/tests/test_security_regression.py -q
```

验收结果：62 passed，耗时 0.35 秒；全量隔离回归 389 passed / 6 skipped。T9 不调用部署 LLM，真实模型质量继续由 Standard MiniBench 承担。

## 18. E3/T10 HVAC RAG 检索与回答 MiniBench

RAG v0.1 使用 10 个基础场景 × 5 种表述生成 50 records，包含 8 类可回答/近邻问题和 2 类不可回答问题。固定语料记录相关 doc_id、检索顺序、去重文档、引用和 low-confidence 期望；Scorer 计算 Recall@5、MRR、nDCG@5、去重率、Citation Precision、Low-confidence Accuracy、Correct Refusal 和 Supported Answer，并将索引缺失、漏标低置信度、低置信度补答、无依据回答、引用超限/非法分别设为 gate。

```bash
python -m benchmarks.runners.run_rag \
  --config benchmarks/configs/fast.yaml \
  --output-dir benchmarks/reports/t10_rag_fast \
  --baseline benchmarks/baselines/rag_v0_1.json
```

Fast 50/50，八项指标全 1.0、gate 0；四类故意错误可触发。50 条真实距离校准证明可回答区间最高 0.4443、不可回答区间最低 0.3004，单一 distance 阈值无法可靠分离；检索层现保留距离判定，并增加可配置的不支持主题 guard。真实 Standard 使用本地 Chroma 快照（5605 documents）和本地 `qwen3.6-35b-a3b` 跑 5 条代表集，八项指标全 1.0、gate 0；量子纠缠与红烧肉均正确标记 `low_confidence=true` 并拒答。T10 完成。

## 19. E3/T11 多意图与最终回答质量 MiniBench

Answer v0.1 包含 30 条多意图执行记录和 40 条回答质量记录，共 70 records；覆盖双/三意图、独立/依赖执行、部分失败、冲突请求，以及标题、单位、风险提示、来源和禁止话术。Scorer 计算 Intent Coverage、Execution Completeness、Dependency Order Accuracy、Section Coverage 和 Deterministic Answer Quality，并分别定位漏执行、顺序错误、漏分段和禁止行为。

```bash
python -m benchmarks.runners.run_answer \
  --config benchmarks/configs/fast.yaml \
  --output-dir benchmarks/reports/t11_answer_fast \
  --baseline benchmarks/baselines/answer_v0_1.json
```

Fast 70/70，五项指标全 1.0、gate 0。修复执行证据缺少导出格式/冲突解决要求、部分失败风险提示契约、分段标题偶发遗漏，以及“调用失败/查询失败”“3条/3 条”等受控同义和排版误判。Standard 使用本地 `qwen3.6-35b-a3b` 跑 5 条代表集，五项指标全 1.0、gate 0。T11 完成。

## 20. E3/T12 SSE、UIAction 与 DataCard 前端契约 MiniBench

UI Contract v0.1 使用 10 个基础场景 × 3 种请求生成 30 records，覆盖 thinking、tool_call、tool_result、rag_sources、text、action、data_card、error、done，以及直接回答、受限路由、空卡片、图表降级、错误和断流恢复。Scorer 计算 SSE Schema、因果顺序、唯一终态、UIAction 合法性、DataCard rows 一致性和最终文本唯一性；硬门禁捕获缺字段、Tool 乱序、缺失/重复 done、受限/未知/重复路由、名称缺失、chart/table/CSV rows 漂移和正文伪造链接。

```bash
python -m benchmarks.runners.run_ui_contract \
  --config benchmarks/configs/fast.yaml \
  --output-dir benchmarks/reports/t12_ui_contract_fast \
  --baseline benchmarks/baselines/ui_contract_v0_1.json
```

Fast 30/30，六项指标全 1.0、gate 0。专项联跑现有真实 SSE 生成器、UIAction 和导出端点共 55 passed；全量隔离回归 413 passed / 6 skipped。T12 为确定性前端协议测试，不调用部署 LLM。

## 21. E4/T13 性能、成本、并发与容量基线

`run_performance` 使用 OpenAI SSE 流分别测量模型 API 首 token/总延迟/token，并可对 EnerGraph `/stream` 测量 First SSE、Final text 和总延迟；支持 warm-up、重复次数、四类负载桶，以及并发 1/2/5/10 的 P50/P95/P99 聚合。

```bash
python -m benchmarks.runners.run_performance \
  --output-dir benchmarks/reports/t13_qwen36_model_agent \
  --base-url http://192.168.128.15:8001/v1 \
  --model qwen3.6-35b-a3b \
  --agent-url http://192.168.128.15:8000 \
  --concurrency 1,2,5,10 --repeats 2 --warmup 1 --max-tokens 64
```

首次完整 Agent 基线暴露两个问题：多 worker 生产模式下每个进程的 RAG embedding/Chroma 懒加载会造成首个 HVAC 请求 20 秒级尖峰；旧 Runner 只看首个正文事件，会把模型排队期间的 SSE 无响应和最终回答延迟混在一起。现已通过 Worker 启动预热和 `/stream` 初始 `thinking` 事件修复首响应口径，并保留 Final text/Total 作为容量指标。

修复后真实基线共执行模型 API 36 请求与完整 Agent 36 请求，成功率均为 100%。模型 API 整体 TTFT P99=381ms、总延迟 P99=1666ms，满足当前 2s 口径；完整 Agent First SSE P99=16.8ms，满足首响应口径。高并发下完整 Agent Final text P99=27.25s、Total P99=32.66s，说明单卡本地 vLLM + 多轮 Agent 在 C=5/10 压测下仍有明显排队，记录为容量风险；后续应通过模型服务扩容、并发限流、链路裁剪或 Tool/LLM 分段遥测继续优化。T13 当前为 **首响应/冷启动问题已修复，容量基线完成，可进入 T14**。

容量风险已有第一层工程保护：`/stream` 支持单 Worker 并发槽限制，默认 `API_MAX_CONCURRENT_STREAMS=4`、`API_STREAM_QUEUE_TIMEOUT_SECONDS=1.0`。并发槽耗尽时接口快速返回 SSE `error` + `done`，避免继续进入 LangGraph/LLM 队列把请求拖成 30 秒级；该保护不替代后续扩容和链路优化，只负责稳定性与用户体验兜底。

## 22. E4/T14 PostgreSQL 与外部服务故障恢复

Fault Recovery v0.1 建立 T14 Fast 门禁，使用 10 个基础场景覆盖 PostgreSQL checkpoint 重启、L2 跨进程读取、连接池耗尽、setup 权限不足、福加 API 401/token refresh、500/timeout、字段缺失、LLM 超时、LLM 流中断和非法 Tool Call。Scorer 计算 Safe Degradation、Isolation Safety、Recovery Consistency、Cleanup Integrity，并对不安全降级、跨域泄漏、故障后编造、恢复不一致、namespace/生产污染设置硬门禁。

Fast 结果为 10/10，四项指标全 1.0，gate 0；故意构造的泄漏、编造、恢复失败和污染均可触发独立 gate。当前完成的是故障恢复验收框架和合成故障门禁，不等同于真实 PostgreSQL/福加 API/服务重启 Production 验收。真实环境执行必须使用独立测试 namespace/DSN/API 凭据，并显式开启，不得误打生产。

Production 故障验收使用专用配置 `benchmarks/configs/fault_recovery_production.yaml`，要求显式设置 `EVAL_FAULT_RECOVERY_PRODUCTION`、`EVAL_NAMESPACE_PREFIX`、`LOCAL_BASE_URL`、`LOCAL_MODEL`、`MEMORY_POSTGRES_DSN`、`FUCA_API_BASE_URL` 和 `FUCA_TENANT_ID`。缺任一项会启动前失败；即使环境变量齐全，当前 `run_fault_recovery` 也会拒绝在 Production 模式继续使用 fixed fixture executor，防止 Fast/Standard 合成结果被误报为生产验收。后续接入真实故障注入执行器后，才可产出 T14 Production 报告。

T13 容量风险已有两层工程保护：`/stream` 支持单 Worker 并发槽限制，默认 `API_MAX_CONCURRENT_STREAMS=4`、`API_STREAM_QUEUE_TIMEOUT_SECONDS=1.0`；并新增 `API_STREAM_EVENT_TIMEOUT_SECONDS=30.0` 和 `API_STREAM_EXECUTION_TIMEOUT_SECONDS=90.0`，在 Graph/LLM 长时间不产出事件或单次执行超过预算时返回 SSE `error` + `done` 并释放并发槽。该保护负责避免卡死和无限排队，不替代后续扩容、链路裁剪和分段遥测。

## 23. E5/T15 企业基线、实验矩阵、CI 与发布治理

T15 将一次性评测沉淀为持续治理能力。`benchmarks/shared/governance.py` 定义三类可测试规则：

- `BaselineUpdateRecord`：baseline 更新必须有不少于 10 字的原因、申请人和独立审批人，且禁止把硬门禁失败结果批准为 baseline；
- `ThresholdChangeRecord`：阈值变更记录 old/new/reason/approver，并明确区分 tighten、relax、unchanged；
- `ReleaseSignoff`：发布签字必须具备可追溯 `RunManifest`、数据集版本、无未解决硬门禁，并默认要求 Production 运行清单。

`benchmarks/configs/ci_matrix.yaml` 固化三档流水线：

- PR：离线、确定性、禁止网络，运行五项 P0 回归和治理规则；
- Daily：可接本地真实 LLM，刷新 Routing/RAG/Answer Standard 趋势；
- Release：真实 LLM、PostgreSQL、福加 API、性能与故障恢复，必须人工签字。

同时记录 Memory、Retrieval、Model 三类实验矩阵和发布必需产物（`run_manifest.json`、`results.json`、`summary.md`、baseline 变更记录或无变更声明）。专项 6 passed，覆盖自批拒绝、硬门禁失败 baseline 拒绝、普通指标波动与硬门禁回归分离、阈值方向、缺 Production 清单和 CI 矩阵结构。
