"""docs/plan_phase_energraph_eval.md — EnerGraph Agent 统一评测体系实施计划

本文为开发计划文档（Markdown），非 Python 模块。
所属层：docs
依赖：CLAUDE.md、AI_CONTEXT.md、PRD.md、docs/plan_memory_module.md
对接算法层：N/A（评测层只验证 Agent 编排与外部接口契约，不实现能源计算）
"""

# EnerGraph Eval — Agent 统一评测 Phase 实施方案

> **版本**：v0.1  
> **创建日期**：2026-07-07  
> **分支**：`feature/energraph-eval-plan`  
> **当前状态**：T0-T6 已完成；下一步 E2/T7 数据忠实度与拒答  
> **核心原则**：记忆评测是完整 Agent Eval 的 P0 模块，不单独建设一套孤立框架。

---

## 1. Phase 目标与边界

### 1.1 总体目标

建立统一、可复现、可分层运行的 `EnerGraph Eval`，覆盖完整助手链路：

```text
用户输入
  → 意图识别
  → Agent / Skill 路由
  → Tool 选择与参数生成
  → 数据获取 / RAG / 记忆检索
  → 回答生成
  → SSE / UIAction / DataCard 下发
```

评测体系必须回答：是否理解意图、是否正确路由和调用工具、是否忠实使用数据、是否安全完整地回答、是否在可接受延迟和成本内稳定运行。

### 1.2 本 Phase 交付物

- `src/tests/`：快速、确定性的 L1 单元测试与 L2 P0 回归门禁；
- `benchmarks/`：L3 MiniBench 数据集、Adapter、Scorer、Runner、报告与基线；
- Fast / Standard / Production 三种运行配置；
- 统一 JSONL 用例规范、结果模型和运行清单；
- P0 硬门禁、质量阈值、基线比较和发布判定；
- L4 真实 LLM、PostgreSQL、福加 API、并发及故障恢复验收手册。

### 1.3 不在本 Phase 中做

- 不在 Agent 代码中实现能源算法或构造预测结果；
- 不替代算法模型自身的数值精度评测；
- 不在默认 CI 中访问真实 LLM、真实 API 或外部 PostgreSQL；
- 不把 LangSmith 或单一供应商绑定为唯一评测后端；
- v0.1 不强制引入复杂 LLM Judge、大规模长对话和在线 A/B；
- 本规划提交阶段不运行任何测试。

---

## 2. 分层运行策略

| 层级 | 目标 | 默认依赖 | 触发频率 | 是否阻断 |
|---|---|---|---|---|
| L1 单元测试 | 函数、Schema、Store、协议正确 | Mock / InMemory | 每次提交 | 是 |
| L2 P0 回归 | 关键业务红线不退化 | Mock LLM / Mock Tool | 每次 PR | 是 |
| L3 MiniBench | 量化 Agent 能力与版本变化 | 固定或真实 LLM，Mock Tool | 每日/手动 | 硬门禁阻断，质量波动告警 |
| L4 发布验收 | 真实环境性能、安全、稳定性 | 真实全链路 | 发布前 | 是 |

### 2.1 三种运行模式

| 模式 | Store | LLM | Tools | 用途 |
|---|---|---|---|---|
| Fast | InMemory | Mock | Mock | 本地开发、提交门禁 |
| Standard | InMemory / PostgreSQL | 固定模型或真实模型 | 固定 Mock | 每日 MiniBench、模型/Prompt 对比 |
| Production | PostgreSQL | 真实本地 LLM | 真实 API/MCP | 发布前验收 |

本地 LLM 未部署时，E0、E1、E2 的 Fast 模式以及 E3 的确定性部分均可建设；真实模型评分必须等服务完成部署并通过接口冒烟后再执行。

截至 2026-07-07，EnerGraph 已通过 OpenAI-compatible API 接入内网 vLLM，实际模型标识为 `qwen3.6-35b-a3b`（模型根目录 `Qwen3.6-35B-A3B-AWQ`）。`/health`、`/v1/models`、模型直呼与 EnerGraph 完整图调用冒烟均通过；后续真实模型评测必须继续在运行清单中记录该 served model ID。

---

## 3. 目标目录

```text
src/tests/
  test_memory_benchmark_regression.py
  test_routing_regression.py
  test_tool_call_regression.py
  test_data_faithfulness_regression.py
  test_security_regression.py

benchmarks/
  README.md
  configs/{fast,standard,production,thresholds}.yaml
  datasets/<module>/v0_1/*.jsonl
  adapters/{graph,api,memory,tool,rag}_adapter.py
  runners/{run_all,run_memory,run_routing,run_tools,...}.py
  scorers/{memory,routing,tool_call,faithfulness,rag,answer,safety,performance}_scorer.py
  shared/{case_loader,result_models,report_generator,run_metadata}.py
  baselines/v0_1.json
  reports/.gitkeep
```

`reports/` 中的运行产物默认不提交，仅保留必要的版本基线和脱敏摘要。

---

## 4. 统一数据与结果契约

### 4.1 用例基础字段

每条 JSONL 用例至少包含：

```json
{
  "case_id": "tool_energy_001",
  "version": "0.1",
  "category": "energy_query",
  "tags": ["routing", "tool_call", "faithfulness"],
  "input": {
    "user_message": "查询江北工厂上周能耗并导出",
    "user_id": "user_a",
    "site_id": "site_jiangbei",
    "thread_id": "thread_001"
  },
  "fixtures": {},
  "expected": {
    "intents": ["energy_range_query", "data_export"],
    "agent": "ui_router",
    "required_tools": ["fetch_energy_range", "export_data_table"],
    "forbidden_tools": [],
    "tool_arguments": {"site_id": "site_jiangbei"},
    "answer_contains": [],
    "answer_forbidden": [],
    "should_reject": false
  }
}
```

模块允许扩展 `turns`、`memory_setup`、`rag_corpus`、`fault_injection`、`security_context` 等字段，但不得改变基础字段语义。

### 4.2 单案例结果

结果至少记录：`run_id`、`case_id`、模式、模型/Prompt/代码版本、实际路由、Tool calls、回答、协议事件、各指标分数、硬门禁、耗时、token、错误与证据摘要。

### 4.3 运行清单

`run_manifest.json` 必须记录 Git commit、工作区是否干净、数据集版本、阈值版本、配置摘要、模型标识、开始/结束时间、随机种子和环境信息；密钥、Token、DSN 密码不得写入报告。

---

## 5. 指标与发布门禁

### 5.1 全局硬门禁

以下任一指标大于 0，当前运行直接失败：

- 跨用户、站点、环境或 Agent 记忆泄漏率；
- 越权 Tool 调用率；
- 无依据能源数值生成率；
- 安全约束违反率；
- 过期或已删除记忆使用率；
- 实时设备状态长期记忆误写率；
- 错误站点数据使用率；
- SSE Schema 非法率；
- DataCard 数据与 Tool rows 不一致率。

### 5.2 v0.1 质量阈值

| 指标 | 阈值 |
|---|---:|
| 单意图准确率 | ≥ 95% |
| Agent 路由准确率 | ≥ 95% |
| Tool Call F1 | ≥ 95% |
| Tool 参数准确率 | ≥ 95% |
| Memory Write Precision | ≥ 95% |
| Memory Write Recall | ≥ 85% |
| Memory Recall@5 | ≥ 90% |
| RAG Recall@5 | ≥ 90% |
| 无答案正确拒答率 | ≥ 90% |
| 多意图执行完整率 | ≥ 90% |
| 最终回答准确率 | ≥ 85% |
| SSE Schema 合法率 | = 100% |
| DataCard 数据一致率 | = 100% |

阈值首次建立前先跑基线、分析失败分布，再由项目负责人确认；禁止为了让当前版本通过而静默降低阈值。

---

## 6. Task 总览与依赖

```text
E0/T0 范围冻结
  └─ E1/T1 契约 → T2 Adapter/配置 → T3 Runner/报告
       └─ E2/T4 Memory ─┬─ T5 Routing ─┬─ T6 Tool Call
                        ├─ T7 Faithfulness
                        ├─ T8 Safety
                        └─ T9 P0 回归门禁
       └─ E3/T10 RAG → T11 多意图/回答 → T12 前端契约
       └─ E4/T13 性能/成本 → T14 PostgreSQL/故障恢复
       └─ E5/T15 基线、Judge、CI 与发布治理
```

每个 Task 原则上独立 commit；Prompt 调整必须与评测代码、数据集改动分开提交。

---

## 7. 具体 Task 规划

### E0 / T0：范围冻结与现状盘点

**目标**：建立评测边界、现有能力清单和差距矩阵，避免重复建设。

**任务**：
- 清点现有 `src/tests/`，标记 L1、外部集成、重复和缺口；
- 从 `TOOL_REGISTRY`、Agent/Skill 注册表、routes、Schema 自动导出能力清单；
- 建立“产品红线 → 指标 → 测试层级 → 责任模块”追踪矩阵；
- 固定 v0.1 名词、case ID、数据集版本和脱敏规则；
- 明确 LLM、PostgreSQL、福加 API 未就绪项及负责人。

**产物**：`benchmarks/README.md` 的范围、术语、追踪矩阵和测试入口章节。

**验收**：所有 PRD 红线都有至少一个计划中的指标与测试层；现有测试没有被误归为真实模型评测。

**依赖**：无。  
**建议 commit**：`[docs] 冻结 EnerGraph Eval v0.1 范围与追踪矩阵`

### E1 / T1：统一 Case、Result 与 Manifest 契约

**目标**：让所有模块共享同一套版本化输入输出。

**任务**：
- 定义 Pydantic Case/Expected/Result/Metric/Gate/Manifest 模型；
- 定义 JSONL 加载、唯一 case_id、必填字段和扩展字段校验；
- 定义敏感字段过滤和确定性序列化；
- 提供最小合法、非法和多轮用例样例；
- 约定 Schema 版本升级与兼容策略。

**文件**：`benchmarks/shared/result_models.py`、`case_loader.py`、`datasets/_examples/`。

**验收**：合法样例可加载；重复 ID、未知版本、非法期望值明确报错；日志不暴露密钥。

**依赖**：T0。  
**建议 commit**：`[schemas] 定义 Eval 用例结果与运行清单契约`

### E1 / T2：运行配置、Fixture 与 Adapter 边界

**目标**：数据集不感知 Graph/API/Store 的具体实现。

**任务**：
- 建立 Fast、Standard、Production 和 thresholds 配置；
- 实现 Graph、API、Memory、Tool、RAG Adapter 接口；
- 建立 Mock LLM 脚本响应与 Mock Tool 固定响应格式；
- 支持 InMemory/PostgreSQL Store 切换和每案例 namespace 清理；
- 实现 timeout、retry、随机种子、并发数等通用参数；
- 配置启动前检查，Production 缺少依赖时快速失败，禁止静默降级。

**文件**：`benchmarks/configs/`、`benchmarks/adapters/`、`benchmarks/fixtures/`。

**验收**：同一用例可经 Fast 和 Standard Adapter 运行；Fast 不访问网络；Production 缺配置时给出明确错误。

**依赖**：T1。  
**建议 commit**：`[test] 建立 Eval 配置 Fixture 与 Adapter 边界`

### E1 / T3：Runner、Scorer 公共框架与报告

**目标**：形成可重复执行、可追溯、可比较的最小评测闭环。

**任务**：
- 实现按模块、tag、case_id、模式选择运行；
- 支持失败隔离、断点续跑和 exit code；
- 实现 scorer 注册、宏/微平均、硬门禁聚合；
- 生成 JSON、Markdown 摘要和 `run_manifest.json`；
- 实现 baseline diff，展示新增失败、已修复、波动指标；
- 报告中保存证据摘要，不保存完整敏感 Tool payload。

**文件**：`benchmarks/runners/run_all.py`、`shared/report_generator.py`、`run_metadata.py`、`scorers/`。

**验收**：最小样例能生成确定性报告；硬门禁失败返回非零退出码；相同输入与种子结果可复现。

**依赖**：T1、T2。  
**建议 commit**：`[test] 建立 Eval Runner Scorer 与报告基线框架`

### E2 / T4：Memory MiniBench（P0）

**目标**：验证抽取、写入、检索、更新、隔离、时效和最终使用。

**任务**：
- 建立用户偏好、站点事实、安全约束、决策历史、设备状态正反样例；
- 覆盖 `memory_key`、upsert、删除、TTL、排序、无答案拒答；
- 覆盖 env/site/user/agent/thread namespace 矩阵；
- 实现 Write P/R/F1、类型/Key 准确率、Recall@5、Precision@5、MRR、Update Accuracy；
- 实现泄漏、过期使用、设备状态误写、安全约束违反硬门禁；
- 提供 InMemory 快速集与 PostgreSQL 发布验收集。

**规模**：v0.1 约 100 个评测记录，可由 60～80 个基础场景组合产生。

**验收**：全部硬门禁可被故意构造的负例触发；Fast 模式不依赖 LLM/PostgreSQL；真实 Store 集独立标记。

**依赖**：T3。  
**建议 commit**：`[test] 建立 Memory MiniBench P0 评测模块`

### E2 / T5：意图识别与 Agent/Skill 路由（P0）

**目标**：验证单意图、相似意图、歧义输入和上下文路由。

**任务**：
- 覆盖 HVAC、运营查询、导出、导航、PowerAI、记忆操作和闲聊；
- 加入同义改写、错别字、时间表达、站点缺失和多轮上下文；
- 检查 intent、agent、skill、拒答/澄清行为；
- 实现 Intent Accuracy、Agent Accuracy、Macro F1、Top-k Accuracy；
- 单独记录 Prompt/模型变化导致的路由漂移。

**规模**：v0.1 80 个评测记录。

**验收**：关键路由均有正例、近邻负例和禁用工具断言；单意图与 Agent 路由达到确认后的阈值。

**依赖**：T3。  
**建议 commit**：`[test] 建立意图与多智能体路由 MiniBench`

### E2 / T6：Tool Call 与参数生成（P0）

**目标**：验证工具名称、次数、顺序、参数、禁止调用及失败路径。

**任务**：
- 为高风险 Tool 建立正常、边界、缺参、非法日期、错误 site_id 用例；
- 检查 required/forbidden/optional tools、调用次数和依赖顺序；
- 参数支持精确、类型、子集、范围和日期语义评分；
- 验证 Tool error、timeout、空数据后不继续编造或错误导出；
- 实现 Tool Precision/Recall/F1、Argument Accuracy、Order Accuracy。

**规模**：v0.1 80 个评测记录。

**验收**：错误站点、越权调用、无数据仍导出假数据能被硬门禁捕获。

**依赖**：T3、T5。  
**建议 commit**：`[test] 建立 Tool Call 与参数准确性 MiniBench`

### E2 / T7：数据忠实度与拒答（P0）

**目标**：保证回答中的数值、单位、时间、来源都能追溯到 Tool/RAG/Memory 证据。

**任务**：
- 从回答抽取数值、单位、日期、实体并与固定证据比对；
- 区分原值、允许格式化、明确推导和禁止自行计算；
- 覆盖部分数据、空数据、冲突数据、工具错误和陈旧数据；
- 验证 CSV/DataCard 与原始 rows 一致；
- 实现 Supported Claim Rate、Numeric Faithfulness、Correct Abstention。

**规模**：v0.1 50 个评测记录。

**验收**：任何无证据能源数值、错误单位、错误站点和假 CSV 均触发硬门禁。

**依赖**：T3、T6。  
**建议 commit**：`[test] 建立数据忠实度与拒答 MiniBench`

### E2 / T8：安全、权限与提示注入（P0）

**目标**：验证身份隔离、工具授权、敏感信息保护和 Prompt Injection 防护。

**任务**：
- 覆盖跨用户/站点/Agent 读取、伪造 site_id、越权导出；
- 覆盖要求泄露 system prompt、Token、DSN、设备 ID；
- 在用户输入、RAG 文档、Tool 返回中注入恶意指令；
- 覆盖绕过拒答、诱导编造、覆盖安全约束；
- 区分阻断、脱敏、拒答和安全降级的预期行为。

**规模**：v0.1 50 个评测记录。

**验收**：所有安全负例均有确定性 gate；报告和日志自身也通过敏感信息扫描。

**依赖**：T3、T4、T6。  
**建议 commit**：`[test] 建立安全权限与提示注入 MiniBench`

### E2 / T9：P0 缺陷沉淀为 L2 回归门禁

**目标**：把 MiniBench 中最高风险且可确定复现的案例沉淀到每 PR 必跑集合。

**任务**：
- 新增 memory、routing、tool、faithfulness、security 五个 regression 文件；
- 每类保留约 10～20 个高风险案例；
- 固定 Mock LLM/Tool，禁止网络和真实 PostgreSQL；
- 约定线上缺陷必须先形成复现案例再修复；
- 控制总运行时间，避免把完整 L3 塞入 pytest。

**验收**：P0 回归可离线、确定性执行；单项失败能指出 case_id 和红线；无外部密钥也可运行。

**依赖**：T4～T8。  
**建议 commit**：`[test] 沉淀五项 P0 关键回归门禁`

### E3 / T10：RAG/HVAC 检索与回答评测

**目标**：同时评估检索质量、引用质量、拒答和答案支持度。

**任务**：
- 建立问题、相关文档 ID、不可回答问题和近邻干扰语料；
- 实现 Recall@k、MRR、nDCG、去重率、Citation Precision；
- 验证 low_confidence 拒答、最多三条来源和不使用模型常识补答；
- 固定 embedding/index 版本和语料快照元数据；
- 将本地索引缺失与质量失败区分报告。

**规模**：v0.1 50 个评测记录。

**验收**：可回答和不可回答集均有覆盖；RAG Recall@5 与拒答率达到阈值。

**依赖**：T3。  
**建议 commit**：`[test] 建立 HVAC RAG 检索回答 MiniBench`

### E3 / T11：多意图与最终回答质量

**目标**：验证多请求识别、完整执行、依赖顺序、分段报告和业务可用性。

**任务**：
- 建立双/三意图、独立/依赖、部分失败和冲突请求；
- 实现 Intent Coverage、Execution Completeness、Dependency Order；
- 确定性检查标题、单位、风险提示、来源、禁止话术；
- 定义人工抽检 rubric；LLM Judge 仅作为可选辅助，不作为 v0.1 唯一门禁；
- Judge 使用时记录模型、Prompt、温度和重复评分一致性。

**规模**：多意图 30 条，回答质量 40 条。

**验收**：多意图完整率达到阈值；确定性规则与人工评分能定位到具体缺陷类别。

**依赖**：T5～T7。  
**建议 commit**：`[test] 建立多意图执行与回答质量 MiniBench`

### E3 / T12：SSE、UIAction 与 DataCard 前端契约

**目标**：验证后端事件与前端消费契约完整、顺序正确且数据一致。

**任务**：
- 覆盖 thinking/tool_call/tool_result/rag_sources/text/action/data_card/done；
- 验证事件 Schema、顺序、唯一 done、最终回答不重复；
- 验证 route 合法性、受限页面、名称填充和去重；
- 验证 DataCard chart/table/download 共用同一 rows；
- 覆盖断流、错误事件、空卡片和图表失败不阻断表格/CSV。

**规模**：v0.1 30 个评测记录。

**验收**：Schema 和 DataCard 一致率 100%；禁止正文伪造链接；终态事件严格唯一。

**依赖**：T3、T6、T7。  
**建议 commit**：`[test] 建立 SSE UIAction DataCard 契约 MiniBench`

### E4 / T13：性能、成本、并发与容量

**目标**：建立可比较的性能预算，不把质量提升建立在不可接受的延迟和成本上。

**任务**：
- 记录首 token、总延迟、Tool/检索/模型分段延迟；
- 记录输入/输出 token、请求成本或本地 GPU 指标；
- 按单轮、多轮、长上下文和多意图分桶；
- 设计并发 1/2/5/10 的阶梯压测和资源观测；
- 设定 warm-up、重复次数、P50/P95/P99 和噪声容忍度。

**验收**：同一环境可重复对比；报告区分模型冷启动、Tool 延迟和 Agent 开销；性能阈值经真实部署基线后确认。

**依赖**：T3；执行依赖本地 LLM 部署完成。  
**建议 commit**：`[test] 建立 Agent 性能成本与并发评测`

### E4 / T14：PostgreSQL 与外部服务故障恢复验收

**目标**：验证真实持久化和外部依赖异常时的可靠性与安全降级。

**任务**：
- 验证 checkpoint 重启恢复、L2 跨进程读取和并发 upsert；
- 验证连接池耗尽、断连、超时、重连、setup 权限不足；
- 验证福加 API 401/500/超时/字段缺失和 Token 刷新；
- 验证 LLM 超时、流中断、非法 tool call 和服务重启；
- 验证备份恢复、数据清理和测试 namespace 不污染生产。

**验收**：故障不导致跨域泄漏或编造；降级行为符合配置；恢复后数据一致；发布验收使用独立测试环境。

**依赖**：T4、T6、T13；执行依赖真实 PostgreSQL、LLM 和 API 环境。  
**建议 commit**：`[test] 建立 PostgreSQL 与外部服务故障恢复验收`

### E5 / T15：企业基线、实验矩阵、CI 与发布治理

**目标**：把评测变成持续工程能力，而非一次性脚本。

**任务**：
- 建立 Oracle Memory、Memory Off、Full History 对照组；
- 比较模型、Prompt、Top-K、检索策略和记忆开关；
- 建立人工标注/复核流程和 LLM Judge 校准集；
- 固化每提交、每日、发布前三档流水线；
- 维护 baseline 审批、阈值变更记录和 flaky case 隔离规则；
- 形成版本趋势、回归分析和发布签字模板。

**验收**：基线更新必须可审计；普通波动与硬门禁区分；任何发布版本都能追溯到运行清单和数据集版本。

**依赖**：T4～T14。  
**建议 commit**：`[test] 建立企业评测基线 CI 与发布治理`

---

## 8. 数据集建设计划

| 模块 | v0.1 评测记录 | 基础场景建议 | 优先级 |
|---|---:|---:|---|
| Memory | 100 | 60～80 | P0 |
| Routing | 80 | 60～80 | P0 |
| Tool Call | 80 | 60～80 | P0 |
| 数据忠实度 | 50 | 30～50 | P0 |
| Safety | 50 | 30～50 | P0 |
| RAG | 50 | 40～50 | P1 |
| 多意图 | 30 | 25～30 | P1 |
| Answer Quality | 40 | 30～40 | P1 |
| SSE/UI Contract | 30 | 20～30 | P1 |

同一基础场景可被多个 scorer 复用，因此不要求创建 510 个完全不同的问题。所有业务数据必须脱敏；禁止把生产会话原文直接提交到仓库。

---

## 9. 执行顺序与里程碑

| 里程碑 | 包含 Task | 完成标志 |
|---|---|---|
| M0 规划冻结 | T0 | 范围、红线、依赖和责任明确 |
| M1 最小评测闭环 | T1～T3 | 示例用例可生成报告和 gate |
| M2 P0 可用 | T4～T9 | 五项 P0 MiniBench + PR 回归门禁 |
| M3 业务完整 | T10～T12 | RAG、多意图、回答和前端契约覆盖 |
| M4 生产验收 | T13～T14 | 真实环境性能与故障恢复完成 |
| M5 企业治理 | T15 | 基线、实验矩阵、CI、发布签字闭环 |

推荐先完成 M0～M2，再接入真实本地 LLM。模型未部署期间不应阻塞 Case/Result 契约、Mock Adapter、P0 数据集和确定性 scorer 的开发。

---

## 10. 风险与控制

| 风险 | 控制措施 |
|---|---|
| 用例过拟合当前 Prompt | 保留改写、对抗、隐藏测试集；Prompt 与数据集版本分离 |
| LLM 结果随机 | 温度固定、多次重复、区分确定性 gate 与统计指标 |
| Judge 偏见/漂移 | 人工校准集、Judge 版本固定、不得作为唯一硬门禁 |
| 真实 API 波动 | Tool Fixture 与真实集分离；真实集只用于 L4 |
| 数据泄漏 | 全量脱敏、日志过滤、独立 namespace、报告不落密钥 |
| 基线被随意更新 | PR 审批、记录原因、禁止自动接受失败结果 |
| 测试套件过慢 | L1/L2/L3/L4 分层，pytest 不承载完整 Benchmark |
| 本地模型尚未就绪 | 先完成 Fast 模式；真实模型任务显式标记依赖 |

---

## 11. Definition of Done

本 Phase 只有在以下条件全部满足时才可标记完成：

1. M1～M5 交付物齐全且文档、Schema、数据集均有版本；
2. 五项 P0 硬门禁在 Fast、Standard、Production 对应环境中均完成验证；
3. 本地真实 LLM、PostgreSQL、福加 API 发布验收均有独立运行清单；
4. 默认 PR 流水线不访问真实外部服务且结果确定；
5. 所有 PRD 红线在追踪矩阵中有可执行测试；
6. 基线更新、阈值调整和失败豁免均可审计；
7. `AI_CONTEXT.md`、`CHANGELOG.md` 和评测 README 同步完成。

---

## 12. 当前下一步

T0-T6 已完成。T6 的 80-record Fast 集六项 Tool 指标全 1.0，三类硬门禁负例均可触发。Standard 使用 `qwen3.6-35b-a3b` 完成 5 条代表集；修正抽象站点、旧导航参数和辅助导航的评测契约后，保存的原始输出重评分 5/5、六项全 1.0、gate 0。再次在线复跑曾偶发超过 120 秒，但终止后 `/health` 仍为 HTTP 200，作为 vLLM 稳定性风险持续观察，不阻塞 T6 功能验收。下一步进入 E2/T7 数据忠实度与拒答 MiniBench。
