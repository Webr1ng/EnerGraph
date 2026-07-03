# EnerGraph — Phase 6: 数据导出（统一 CSV 模板）

> 本文件是 Phase 6 的单点真相。
> **最后更新**: 2026-07-03 · **状态**: ✅ 完成（自动图表 + 表格 + CSV）

## 目标

让 Agent 能够查询多日历史数据，以**自动推荐图表 + 表格 + CSV 下载**形式下发给前端。

- **前置条件**: Phase 2 完成（SSE + Java 后端工具体系可用）✅
- **实现范围**: 真实范围数据导出 + 折线图/柱状图/饼图自动推荐
- **完成标志**: 用户问「导出最近 7 天能耗数据」→ Agent 调用 `fetch_energy_range` + `export_data_table`，SSE 推送 `event: data_card`，前端渲染表格 + 下载按钮，`GET /export/{task_id}` 返回 CSV。

---

## 核心架构原则：统一导出模板

**导出能力是统一模板，新增可导出数据类型无需重新开发。**

| 抽象 | 实现 | 复用范围 |
|------|------|----------|
| 通用导出工具 | `export_data_table(title, columns, rows, chart_hint)` —— 推荐图表并生成 CSV | 所有数据类型 |
| 通用 SSE 事件 | `event: data_card` —— DataCard 含 table + download | 所有数据类型 |
| 通用下载端点 | `GET /export/{task_id}` —— uuid hex 防穿越，无鉴权 | 所有数据类型 |
| 通用前端渲染 | `st.dataframe` + `st.download_button` | 所有数据类型 |

**新增可导出数据类型（如光伏发电、光伏预测）只需**：
1. 新增该数据的 range fetch 工具（如 `fetch_pv_range`）；
2. 在 `prompts/main_graph.yaml` 的「数据导出规则」段补一行映射。

`export_data_table` 与整条下载链路全部复用，零改动。日期范围自定义：`start_date`/`end_date` 参数，LLM 解析「最近 N 天」=今天往前推 N 天（YYYY-MM-DD），agent 自动识别执行。

---

## 业务场景

### 场景 1: 能耗多日 + 表格下载
用户问：「导出最近 7 天江北工厂能耗数据」

Agent 应：
1. 解析日期范围（最近 7 天 = 今天往前推 6 天，含今天）；
2. 调用 `fetch_energy_range(site_id, start_date, end_date)` 获取多日能耗；
3. 调用 `export_data_table(title, columns, rows)` 生成 CSV（columns 用中文表头 + 单位，rows 取 items）；
4. 回答正文给数据总结（总量、均值、峰值日期），表格与下载由前端自动渲染。

### 场景 2: 报警历史导出
用户问：「导出本月报警记录」

Agent 应：
1. 调用 `fetch_alarm_history(site_id, start_date, end_date)` 获取历史报警明细；
2. 调用 `export_data_table` 生成 CSV；
3. 同时附带「查看页面」跳转（`/alarm/history`）。

### 场景 3: 图表可视化（✅ 已实现）
`recommend_chart` 根据真实 rows 推荐图表：时间+数值为折线图、分类+数值为柱状图、明确构成语义为饼图；数据不足时仅下发表格与 CSV。

为控制前端复杂度，协议保持单个 `chart`：单图最多 4 个同单位系列；不同单位不会进入同一坐标轴。被过滤的字段仍完整保留在 `table.rows` 和 CSV 中。后端只输出 JSON 字段映射，不生成图片或完整 ECharts option；Streamlit 图表仅用于开发预览。

排名柱状图额外输出轻量展示提示：按数值降序、柱顶显示数值、第一名高亮、单系列隐藏图例、横轴标签旋转 45°。排序仅用于图表显示，不改变 `table.rows` 与 CSV 原始顺序。

构成数据支持 `pie` 与 `donut`：两者均隐藏集中图例，在对应扇区外侧标注类别和百分比。环形图只新增一种轻量类型，不携带第二份数据。

---

## SSE 协议扩展

在现有事件基础上新增 `event: data_card`：

| 事件类型 | 用途 | 触发时机 |
|----------|------|----------|
| `event: text` | LLM token 流 | 每次 LLM 生成 |
| `event: action` | 页面跳转信号 | UIAction navigate |
| **`event: data_card`** | **结构化数据卡片（表格 + 下载）** | **`export_data_table` 生成** |
| `event: done` | 流结束 | 图执行完毕 |
| `event: error` | 错误信息 | 异常 |

DataCard 载荷结构（`src/schemas/data_card.py`）：
```json
{
  "card_type": "table",
  "title": "FJJB000001 近7天能耗汇总",
  "table": {
    "columns": [{"key": "date", "label": "日期", "unit": ""},
                {"key": "total_consumption_kwh", "label": "总用电量", "unit": "kWh"}],
    "rows": [{"date": "2026-06-20", "total_consumption_kwh": 1234.5}, ...]
  },
  "download": {"format": "csv", "filename": "xxx.csv", "url": "/export/{task_id}", "task_id": "..."}
}
```

---

## 关键设计决策

**1. LLM 显式驱动导出（非 Skill 自动推断）**
LLM 取到多日数据后，**显式调用** `export_data_table(title, columns, rows)` 生成 CSV。LLM 掌控中文表头/单位/列选择 → UX 更好；工具=确定性文件 I/O，符合架构红线（Agent 不做业务计算）。老 plan 的 `infer_data_card` 自动推断改为 LLM 显式调用，更可控、更通用。`UIRouterSkill._infer_data_cards` 仅做透传：收集 `export_data_table` 的成功结果作为 `pending_data_cards` 下发。

**2. 多日数据获取：循环复用已验证的真实 API 工具**
- `fetch_energy_range` 逐日调用 `fetch_energy_summary`（已对接 ECInfo + supplyAndDemandList），跳过含 error 的日期。
- `fetch_alarm_history` 复用 `listHisAlarms`（与 `fetch_monthly_alarm_count` 同源的 POST 接口）按日期范围取明细，字段解析复用 `fetch_active_alarms` 的 `_alarm_level_str` / `AlarmItem` 构造。
- 无 API 配置时返回 `{"error": ...}`（沿用 2026-06-25 起的去 Mock 策略，不返随机数）。

**3. `GET /export/{task_id}` 不鉴权**
task_id = uuid4 不可猜、文件短期 ephemeral；`<a href>` 下载链接无法带 Bearer 头。与 `/health` 一致开放。task_id 用 hex 字符集 allowlist 校验（排除 `/`、`.`、`\`），防路径穿越。

**4. DataCard 独立 SSE 事件 + 独立 state 字段**
不混入 `UIAction`。`chart` 只描述字段映射，不携带第二份数据；图表、表格和 CSV 始终共用 `table.rows`。

**5. 为什么扩展现有 UIRouterSkill 而非新建 DataExportSkill？**
数据导出是监控查询的自然延伸（查数据 → 看数据 → 导出数据），与 UIRouterSkill 职责天然耦合。新建 Skill 会导致两个 Skill 调用相同工具。若后续导出逻辑超过 200 行，可拆分为独立 Skill。

**6. 为什么用独立 `DataCard` 模型而非扩展 UIAction？**
UIAction 的 `route` 字段对数据卡片无意义。DataCard 有自己的结构化字段（columns/rows/download），混入 UIAction 会破坏简洁性。两者通过独立 SSE 事件下发，前端分别处理。

---

## 文件清单

### 新增文件
| 文件 | 职责 |
|------|------|
| `src/schemas/data_card.py` | `ColumnDef` / `TableData` / `DownloadInfo` / `DataCard` Pydantic 模型 |
| `src/tools/export_data.py` | `export_data_table`：生成 CSV 临时文件 + 返回 DataCard（含下载 URL） |
| `src/utils/chart_recommender.py` | 根据列结构与 `chart_hint` 推荐 line/bar/pie |
| `src/tests/test_data_export.py` | 工具/Skill/endpoint/SSE 全链路单测（24 例） |

### 修改文件
| 文件 | 改动 |
|------|------|
| `src/tools/java_backend.py` | 新增 `fetch_energy_range` + `fetch_alarm_history`（多日/范围查询） |
| `src/tools/__init__.py` | 注册 `fetch_energy_range` / `fetch_alarm_history` / `export_data_table` 到 `TOOL_REGISTRY` + `TOOL_SCHEMAS` |
| `src/graph/state.py` | 新增 `pending_data_cards: Annotated[List[dict], operator.add]` |
| `src/skills/ui_router_skill.py` | `tools` 追加 3 工具；`execute` 调 `_infer_data_cards`；新增 `_infer_data_cards` 静态方法 |
| `config/routes.yaml` | `/analysis/consumption-panel` 追加 `fetch_energy_range`；`/alarm/history` 追加 `fetch_alarm_history` |
| `src/config/prompts/main_graph.yaml` | `cognitive_parser.system` 新增「数据导出规则」段（通用写法） |
| `src/services/api.py` | SSE 新增 `event: data_card`；新增 `GET /export/{task_id}`；`/invoke` 返回 `data_cards` |
| `src/frontend/app.py` | Vega-Lite 渲染图表，同时保留表格与下载按钮 |

---

## 实现步骤（已完成，按 commit）

| Commit | 标签 | 内容 |
|--------|------|------|
| 1 | `[schemas]` | `data_card.py` + `AgentState.pending_data_cards` |
| 2 | `[tools]` | `fetch_energy_range` + `fetch_alarm_history` + `export_data_table` + 注册 |
| 3 | `[refactor]` | `UIRouterSkill._infer_data_cards` + `routes.yaml` |
| 4 | `[config]` | `cognitive_parser` 数据导出规则 prompt（单独 commit） |
| 5 | `[frontend]` | SSE `data_card` 事件 + `/export` 端点 + Streamlit 渲染 |
| 6 | `[test]` | `test_data_export.py`（24 例） |
| 7 | `[docs]` | 本文件 + 删除老 plan + AI_CONTEXT/CHANGELOG 同步 |

分支：`feature/phase6-export` → PR → `main`。

---

## 验证

1. `conda run -n energraph python -m compileall src` 通过 ✅
2. `conda run -n energraph pytest src/tests/test_data_export.py -q` 全绿（24 passed）✅
3. `conda run -n energraph pytest src/tests/ -q` 无回归（122 passed / 6 skipped）✅
4. SSE：`curl -N -X POST http://localhost:8000/stream -H "Content-Type: application/json" -d '{"user_input":"导出最近7天能耗数据","page_context":{"site_id":"FJJB000001"}}'`（需 `.env` 配 `FUCA_API_BASE_URL`）→ 见 `event: data_card` + `tool_call(fetch_energy_range/export_data_table)`
5. 报警导出：同上，输入「导出本月报警记录」→ 走 `fetch_alarm_history`
6. 下载：`curl http://localhost:8000/export/{task_id} -o test.csv` → 可被 Excel/Numbers 打开（utf-8-sig BOM）
7. Streamlit：`conda run -n energraph streamlit run src/frontend/app.py`，侧边栏「📊 数据导出测试」→ 表格 + 下载按钮

---

## 待确认 / 风险

- **Java 多日范围 API**：当前循环单日接口次优。后续若发现原生 range 接口再替换 `fetch_energy_range` 内部实现（签名不变，对 LLM 透明）。
- **listHisAlarms 字段**：假设与 listRealAlarms 同 shape（alarmInfoId/alarmLevel/deviceName/alarmContent/firstTime/recoverTime）；若字段差异则适配 `fetch_alarm_history` 解析。
- **图表语义**：饼图仅用于明确的整体构成；数据不足时安全退化为表格与 CSV。
- **未来数据类型扩展**：光伏发电/光伏预测等导出，按「统一模板」原则仅需新增 range fetch 工具 + prompt 一行，本期架构已预留。
