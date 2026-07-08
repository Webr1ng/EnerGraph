# EnerGraph Eval v0.1

本目录承载 EnerGraph 的统一离线评测与发布验收资产。v0.1 只评估 Agent 的意图理解、路由、工具编排、证据使用、记忆、回答和前端协议，不评估算法模型自身的预测或优化精度，也不在评测代码中实现能源计算。

## 1. 分层与测试入口

| 层级 | 范围 | 默认依赖 | 入口 | 当前状态 |
|---|---|---|---|---|
| L1 | 函数、Schema、Store、协议 | Mock / InMemory | 见下方 Fast 基线命令 | 已有，318 cases |
| L2 | P0 确定性回归门禁 | Mock LLM / Mock Tool | 后续 `src/tests/test_*_regression.py` | E2/T9 建设 |
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

支持 `--case-id`、`--tag`、`--category` 筛选，`--resume` 断点续跑，`--baseline` 比较新增失败、已修复失败和指标变化。报告固定生成 `results.json`、`summary.md`、`run_manifest.json`，运行产物由 `.gitignore` 排除；版本基线放 `benchmarks/baselines/`。

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

T4 验收结果：InMemory 与本机 PostgreSQL 各 100 cases，Write P/R/F1、类型/Key准确率、Recall@5、Precision@5、MRR、Update Accuracy 均为 1.0，硬门禁 0。故意构造的跨 namespace 泄漏、过期使用、删除后使用、安全约束违反和设备状态无 TTL 写入均能触发对应 gate。PostgreSQL 使用 `energraph_eval_memory/eval` 独立前缀并逐案例清理。当前产品代码没有公开 delete API，因此“删除后真实 Store 不可读”尚不能执行，只验证了 scorer 门禁；该能力缺口留待记忆模块或 T14 补齐，不伪造通过。

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

Fast 结果为 80/80，六项指标全 1.0，硬门禁 0；故意构造的越权 Tool、错误站点和 Tool error/空数据后假导出均能触发 gate。Standard 使用 `qwen3.6-35b-a3b` 完成能耗、COP、导航、HVAC、非法日期 5 条代表集。首次报告暴露评测契约仍沿用抽象 `site_demo`、旧导航 `keyword`，且未将数据查询后的合法 `navigate_to_page` 视为 optional；对齐注册站点 `FJJB000001`、真实 `route` 参数及 Tool 默认当天语义后，保存的原始结果重评分 5/5，六项全 1.0、gate 0。再次在线复跑偶发超过 120 秒，终止后 health 仍为 200，作为 vLLM 稳定性风险记录；T6 功能验收完成。
