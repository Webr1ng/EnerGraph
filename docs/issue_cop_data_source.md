# Issue：`fetch_cop_data` 数据源与首页 COP 口径不一致

> **状态**：⏳ 待处理（暂不修改，已记录）  
> **发现日期**：2026-06-30  
> **严重度**：中（数据可读、不崩溃，但与用户在福加首页看到的数值对不上，影响信任度）  
> **关联模块**：`src/tools/java_backend.py` → `fetch_cop_data`

---

## 1. 问题现象

用户问「冷水机房 COP 多少？」时，Agent 回答的 COP 数值与用户在**福加首页**看到的对不上：

| 指标 | Agent 回答（`fetch_cop_data`） | 福加首页显示 |
|------|-------------------------------|-------------|
| 机房瞬时 COP | **6.3**（取自「水系统瞬时SCOP」） | **6.10** |
| 机房累计 COP | **7.7**（取自「水系统平均SCOP」） | **7.00** |
| 机组瞬时 COP | ❌ 未返回 | 7.30 |
| 机组累计 COP | ❌ 未返回 | 9.40 |

Agent 另返回了首页 COP 面板没有的字段：瞬时功率 70.2 kW、冷水出水温度 7.4°C、冷却水进水温度 27.0°C。

---

## 2. 根因：三个接口，`fetch_cop_data` 用的是第三个

| 口径 | 接口 | 取值字段/点位 | 谁在用 |
|------|------|--------------|--------|
| **首页 COP** | `GET /integrateMonitor/cockpit/roomEnergy` | `copInstant` / `copAvg` / `unitCopInstant` / `unitCopAvg` | 首页自动加载；`fetch_device_rank(rank_type="room")` 已取 `copInstant`/`copAvg` |
| **agent COP** | `POST /integrateMonitor/chillerRoom/getValueByPointGroupNames` | 点位 `水系统瞬时SCOP` / `水系统平均SCOP` / `水系统瞬时功率` | `fetch_cop_data`（当前） |
| 能效查询页（时间序列） | `POST /analysisWeb/efficiencyQuery/v1/queryPointEnergyEfficiency` | 按点位 id 查逐时曲线 | `fetch_efficiency_detail` |

**结论**：`fetch_cop_data` 用的**既不是首页接口，也不是能效查询接口**，而是 `getValueByPointGroupNames` + 「水系统 SCOP」点位。首页 COP 走的是 `cockpit/roomEnergy` 聚合接口的 `copInstant`/`copAvg` 字段。两个不同接口、不同口径，数值自然不一致。

---

## 3. 代码位置

- **`fetch_cop_data` 实现**：[`src/tools/java_backend.py:345-417`](../src/tools/java_backend.py#L345-L417)
  - COP 点位取值：[`java_backend.py:368-376`](../src/tools/java_backend.py#L368-L376)
    ```python
    point_names = ["水系统平均SCOP", "水系统瞬时SCOP", "水系统瞬时功率"]
    instant_cop = _to_float(cop_data.get("水系统瞬时SCOP"))    # → 6.3
    cumulative_cop = _to_float(cop_data.get("水系统平均SCOP"))  # → 7.7
    ```
  - 底层接口：`_query_point_group_names` → `POST /integrateMonitor/chillerRoom/getValueByPointGroupNames`（[`java_backend.py:313`](../src/tools/java_backend.py#L313)）
- **点位配置**：[`config/site_mapping.yaml:17-19`](../config/site_mapping.yaml#L17-L19)（注释声称「水系统平均SCOP = 机房累计COP」，但实测 7.7 ≠ 首页 7.00，映射不准）
- **首页 COP 接口抓包**：[`docs/api_capture_batch1.md:100-103`](api_capture_batch1.md#L100-L103)
  - 字段映射：`data.copInstant`→机房瞬时COP、`data.copAvg`→机房累计COP、`data.unitCopInstant`→机组瞬时COP、`data.unitCopAvg`→机组累计COP
- **已有先例**：`fetch_device_rank(rank_type="room")` 已在 [`java_backend.py:789-802`](../src/tools/java_backend.py#L789-L802) 调 `cockpit/roomEnergy` 并取 `room_cop_instant=copInstant`、`room_cop_avg=copAvg`
- **修正史佐证**：[`docs/api_capture_batch1.md:33-34`](api_capture_batch1.md#L33-L34)——历史最终定准机房 COP 用「水系统累计COP」(=7.0)，而非当前用的「水系统平均SCOP」(=7.7)

---

## 4. 影响范围

- `fetch_cop_data` 是 COP 查询的唯一入口，所有「机房 COP / 能效 / 冷水机组性能」类问题都走它，返回值都与首页口径有偏差。
- 缺机组级 COP（`unitCopInstant`/`unitCopAvg`），用户问「机组 COP」时 Agent 无数据。
- 不影响：报警、能耗、光伏、预测等其他工具。

---

## 5. 修复建议（待用户确认后实施）

让 `fetch_cop_data` 的 **COP 主源改用 `cockpit/roomEnergy`**，与首页同源：

| 字段 | 来源 |
|------|------|
| `instant_cop` | `cockpit/roomEnergy.copInstant`（机房瞬时） |
| `cumulative_cop` | `cockpit/roomEnergy.copAvg`（机房累计） |
| 新增 `unit_instant_cop` | `cockpit/roomEnergy.unitCopInstant`（机组瞬时） |
| 新增 `unit_cumulative_cop` | `cockpit/roomEnergy.unitCopAvg`（机组累计） |
| `power_kw` | 仍用 `getValueByPointGroupNames` 的「水系统瞬时功率」点位 |
| 蒸发器/冷凝器温度 | 仍用 `getDeviceRunningInfo` |

**合规性**：仅切换福加 REST 接口，不在 Python 里手写能效计算，不违反「Agent 不做计算」架构红线。  
**测试**：改后需更新 `src/tests/` 中 `fetch_cop_data` 相关用例的 mock 响应（从点位 dict 改为 `copInstant/copAvg/...` 结构），并对齐首页实测数值。

---

## 6. 临时应对（修复前）

- 回答用户 COP 时，可同时调 `fetch_device_rank(rank_type="room")` 取 `room_cop_instant`/`room_cop_avg`（首页口径），与 `fetch_cop_data` 互补；或在 prompt 里注明「`fetch_cop_data` 的 COP 为水系统 SCOP 口径，与首页机房 COP 可能有差异」。
- 根治仍需按 §5 改 `fetch_cop_data` 数据源。

---

> 本 issue 修复前请勿删除；修复后在本文件顶部将状态改为 ✅ 已修复并补 commit 号。
