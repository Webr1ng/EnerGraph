# EnerGraph Agent API — 前端对接指南

> 本文档面向前端开发人员，包含接口定义、Vue.js 代码示例和 TypeScript 类型定义。

---

## 目录

1. [快速开始](#1-快速开始)
2. [接口总览](#2-接口总览)
3. [请求体定义](#3-请求体定义)
4. [/invoke 同步接口](#4-invoke-同步接口)
5. [/stream 流式接口（SSE）](#5-stream-流式接口sse)
6. [TypeScript 类型定义](#6-typescript-类型定义)
7. [Vue 组件示例](#7-vue-组件示例)
8. [页面跳转处理](#8-页面跳转处理)
9. [错误处理](#9-错误处理)
10. [常见问题](#10-常见问题)
11. [数据导出对接（Phase 6）](#11-数据导出对接phase-6)

---

## 1. 快速开始

### 1.1 环境准备

```bash
# Python 环境（conda）
conda activate energraph

# 启动 API 服务
python run.py
```

启动后访问 `http://localhost:8000/docs` 可查看 Swagger 交互文档。

### 1.2 验证连通

```bash
curl http://localhost:8000/health
# 返回: {"status": "ok"}
```

### 1.3 鉴权

如果后端配置了 `API_KEY`，所有请求需携带 Bearer Token：

```
Authorization: Bearer <api_key>
```

`/health` 端点不需要鉴权。

---

## 2. 接口总览

| 端点 | 方法 | 说明 | 鉴权 |
|------|------|------|------|
| `/health` | GET | 健康检查 | ❌ |
| `/invoke` | POST | 同步调用，返回完整报告 | ✅ |
| `/stream` | POST | SSE 流式调用，逐 token 推送 | ✅ |
| `/export/{task_id}` | GET | 下载导出的 CSV 文件（Phase 6 数据导出） | ❌ |

**Base URL**: 开发环境 `http://localhost:8000`，生产环境由后端配置。

**推荐**: 生产环境使用 `/stream` 接口，用户体验更好（实时打字效果）。

---

## 3. 请求体定义

### 3.1 POST Body（`/invoke` 和 `/stream` 共用）

```json
{
  "user_input": "查看冷站COP",
  "page_context": {
    "current_route": "/chiller-room",
    "site_id": "FJJB000001",
    "params": {},
    "meta": {}
  }
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `user_input` | `string` | ✅ | 用户输入文本 |
| `page_context` | `object` | ❌ | 当前页面上下文 |
| `page_context.current_route` | `string` | ❌ | 当前页面路由，默认 `/` |
| `page_context.site_id` | `string` | ❌ | 当前选中站点 ID |
| `page_context.params` | `object` | ❌ | 页面级参数（筛选条件、选中设备等） |
| `page_context.meta` | `object` | ❌ | 扩展元数据 |

> **提示**: `page_context` 帮助 Agent 理解用户当前所在的页面，从而给出更精准的导航建议。建议每次请求都传入。

---

## 4. /invoke 同步接口

### 4.1 请求

```
POST /invoke
Content-Type: application/json
```

### 4.2 响应

```json
{
  "report": "## 冷站 COP 分析\n\n当前冷站瞬时 COP 为 **4.2**...",
  "actions": [
    {
      "type": "navigate",
      "route": "/chiller-room/detail",
      "params": { "chiller_id": "CW-01" },
      "meta": {}
    }
  ],
  "data_cards": []
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `report` | `string` | Markdown 格式的分析报告 |
| `actions` | `UIAction[]` | Agent 建议的 UI 动作列表（页面跳转等） |
| `data_cards` | `DataCard[]` | 数据卡片列表（推荐图表 + 表格 + 下载按钮）。无导出意图时为空数组。详见 [§11](#11-数据导出对接phase-6) |

### 4.3 HTTP 状态码

| 状态码 | 说明 |
|--------|------|
| 200 | 成功 |
| 401 | API Key 无效 |
| 500 | Agent 执行失败（`detail` 字段包含错误信息） |

---

## 5. /stream 流式接口（SSE）

### 5.1 请求

```
POST /stream
Content-Type: application/json
```

### 5.2 SSE 事件类型

流式接口返回 `text/event-stream`，包含以下事件类型：

| 事件类型 | 说明 | 前端建议 |
|----------|------|----------|
| `thinking` | Agent 思考过程（工具调用前的推理） | 可折叠/丢弃 |
| `tool_call` | 工具调用（name + args） | 可折叠/丢弃 |
| `tool_result` | 工具返回结果（name + result） | 可折叠/丢弃 |
| `rag_sources` | RAG 知识库检索来源 | 可折叠/展示为引用 |
| `text` | 最终回答文本（流式） | **主体内容，必须展示** |
| `intent_plan` | 多意图识别计划 | 可折叠 |
| `action` | UI 动作（页面跳转等） | 渲染为按钮或自动执行 |
| `data_card` | 数据卡片（推荐图表 + 表格 + CSV） | 渲染图表、表格和下载按钮 |
| `error` | 错误信息 | 展示给用户 |
| `done` | 流结束标志 | 停止加载状态 |

#### `thinking` — Agent 思考过程

```
event: thinking
data: {"text": "用户问的是机房COP，我需要调用"}
```

工具调用前 cognitive_parser 的推理文本。前端可选择折叠或丢弃。

#### `tool_call` — 工具调用

```
event: tool_call
data: {"name": "fetch_cop_data", "args": {"site_id": "FJJB000001", "chiller_id": "CH-01"}}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | `string` | 工具名称 |
| `args` | `object` | 工具参数 |

#### `tool_result` — 工具返回结果

```
event: tool_result
data: {"name": "fetch_cop_data", "result": {"cumulative_cop": 7.0, "instant_cop": 7.4, ...}}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | `string` | 工具名称 |
| `result` | `object` | 工具返回的 JSON 数据 |

#### `rag_sources` — RAG 知识库检索来源

```
event: rag_sources
data: {"query": "含湿量与相对湿度的区别", "results": ["问题：...\n回答：...", ...]}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `query` | `string` | 检索查询 |
| `results` | `string[]` | 检索到的知识片段列表 |

前端可展示为"参考来源"或引用标注。

#### `text` — 最终回答文本

```
event: text
data: {"text": "当前冷站的"}
```

前端应将每个 `text` 事件的内容追加到报告文本中，实现打字机效果。**这是主体回答内容，必须展示。**

#### `intent_plan` — 多意图识别计划

```
event: intent_plan
data: {
  "intents": [
    {"id": 1, "description": "查看冷站COP", "category": "monitor", "depends_on": [], "status": "pending"},
    {"id": 2, "description": "检查报警信息", "category": "alarm", "depends_on": [], "status": "pending"}
  ]
}
```

| IntentItem 字段 | 类型 | 说明 |
|-----------------|------|------|
| `id` | `number` | 意图序号 |
| `description` | `string` | 意图描述 |
| `category` | `string` | 类别：`hvac` / `monitor` / `energy` / `alarm` / `export` / `general` |
| `depends_on` | `number[]` | 依赖的意图 ID |
| `status` | `string` | 状态：`pending` / `running` / `done` / `failed` |

#### `action` — UI 动作

```
event: action
data: {"type": "navigate", "route": "/chiller-room", "params": {"site_id": "FJJB000001"}, "meta": {}}
```

#### `data_card` — 数据卡片（Phase 6 导出）

用户表达导出意图时，Agent 用同一批真实 rows 生成推荐图表、表格和 CSV，并通过本事件下发 DataCard。

```
event: data_card
data: {
  "card_type": "table_chart",
  "title": "FJJB000001 近7天能耗汇总（2026-06-20 ~ 2026-06-26）",
  "table": {
    "columns": [
      {"key": "date", "label": "日期", "unit": ""},
      {"key": "total_consumption_kwh", "label": "总用电量", "unit": "kWh"}
    ],
    "rows": [
      {"date": "2026-06-20", "total_consumption_kwh": 3080.8},
      {"date": "2026-06-21", "total_consumption_kwh": 3370.0}
    ]
  },
  "chart": {
    "type": "line",
    "x_axis": {"key": "date", "label": "日期", "unit": ""},
    "series": [{"key": "total_consumption_kwh", "label": "总用电量", "unit": "kWh"}],
    "reason": "时间维度配合连续数值，适合展示变化趋势"
  },
  "download": {
    "format": "csv",
    "filename": "FJJB000001_近7天能耗_20260620_20260626.csv",
    "url": "/export/3494886268da49fd98eb0d1174aca4ee",
    "task_id": "3494886268da49fd98eb0d1174aca4ee"
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `card_type` | `string` | `"table"` 或 `"table_chart"` |
| `title` | `string` | 卡片标题，可直接用于 UI 展示 |
| `table.columns` | `ColumnDef[]` | 列定义，`key` 对应 rows 字段名，`label` 为中文表头，`unit` 为单位（可为空） |
| `table.rows` | `object[]` | 行数据，每行为 `{key: value, ...}` |
| `chart` | `ChartSpec \| null` | 推荐图表；所有图表值必须读取 `table.rows` |
| `download.format` | `string` | 文件格式，当前固定 `"csv"` |
| `download.filename` | `string` | 建议的下载文件名 |
| `download.url` | `string` | 下载 URL（`/export/{task_id}`），拼接 Base URL 后可直接 GET |
| `download.task_id` | `string` | 导出任务 ID（uuid hex） |

> **前端处理建议**：
> - **表格**：按 `columns` 顺序渲染表头（`label` + 单位），行按 `key` 取值。推荐用 `<table>` 或表格组件。
> - **下载按钮**：`<a href="${BASE_URL}${download.url}" download="${download.filename}">⬇️ 下载 CSV</a>`，无需带 Authorization 头（端点不鉴权）。
> - **CSV 编码**：文件为 utf-8-sig（含 BOM），Excel/Numbers 可直接打开中文不乱码。
> - **时效**：导出文件短期 ephemeral，过期后 `/export/{task_id}` 返回 404，前端应容错（如隐藏按钮或提示重新导出）。

#### `error` — 错误

```
event: error
data: {"error": "Agent 执行超时"}
```

#### `done` — 流结束

```
event: done
data: {}
```

收到 `done` 事件后，流式传输完成。

---

## 6. TypeScript 类型定义

将以下类型定义放入项目的 `types/agent.d.ts`：

```typescript
// ── 请求 ──────────────────────────────────────────────

/** 页面上下文 */
interface PageContext {
  current_route: string;
  site_id?: string | null;
  params: Record<string, unknown>;
  meta: Record<string, unknown>;
}

/** 请求体 */
interface AgentRequest {
  user_input: string;
  thread_id?: string;
  user_id?: string; // 登录用户稳定 ID；用于长期偏好隔离，不要使用临时 session ID
  page_context?: PageContext;
}

// ── 响应 ──────────────────────────────────────────────

/** UI 动作 */
interface UIAction {
  type: string;        // "navigate" | "highlight" | "open_panel"（后续扩展）
  route: string;       // 目标路由（始终以 / 开头，如 "/analysis/consumption-panel"）
  name: string;        // 页面名称（如 "能耗分析"、"设备运行"），从 routes.yaml 自动填充
  params: Record<string, unknown>;
  meta: Record<string, unknown>;
}

/** 数据卡片列定义（Phase 6 导出） */
interface ColumnDef {
  key: string;         // 行数据中对应字段名（snake_case）
  label: string;       // 表头显示文本（中文）
  unit?: string;       // 单位（如 kWh / ℃），可为空
}

/** 表格数据 */
interface TableData {
  columns: ColumnDef[];
  rows: Record<string, unknown>[];
}

interface ChartSpec {
  type: 'line' | 'bar' | 'pie';
  x_axis: ColumnDef;
  series: ColumnDef[];
  reason: string;
  sort: 'none' | 'asc' | 'desc';
  show_values: boolean;
  highlight_top: boolean;
  show_legend: boolean;
  x_label_angle: number;
}

/** 下载信息 */
interface DownloadInfo {
  format: string;      // 文件格式，当前固定 "csv"
  filename: string;    // 下载文件名
  url: string;         // 下载 URL（/export/{task_id}），拼接 Base URL 后 GET
  task_id: string;     // 导出任务 ID（uuid hex）
}

/** 数据卡片（Phase 6 导出：推荐图表 + 表格 + 下载） */
interface DataCard {
  card_type: 'table' | 'table_chart';
  title: string;       // 卡片标题
  table: TableData;    // 表格数据
  chart?: ChartSpec | null;
  download: DownloadInfo; // 下载信息
}

/** /invoke 响应 */
interface AgentInvokeResponse {
  report: string;      // Markdown 格式报告
  actions: UIAction[]; // UI 动作列表
  data_cards: DataCard[]; // 数据卡片列表（Phase 6 导出，无导出意图时为空数组）
}

/** 多意图项 */
interface IntentItem {
  id: number;
  description: string;
  category: 'hvac' | 'monitor' | 'energy' | 'alarm' | 'export' | 'general';
  depends_on: number[];
  status: 'pending' | 'running' | 'done' | 'failed';
}

// ── SSE 事件 ──────────────────────────────────────────

/** thinking 事件（思考过程） */
interface SSEThinkingEvent {
  text: string;
}

/** tool_call 事件（工具调用） */
interface SSEToolCallEvent {
  name: string;
  args: Record<string, unknown>;
}

/** tool_result 事件（工具结果） */
interface SSEToolResultEvent {
  name: string;
  result: Record<string, unknown> | string;
}

/** rag_sources 事件（RAG 来源） */
interface SSERagSourcesEvent {
  query: string;
  results: string[];
}

/** text 事件（最终回答） */
interface SSETextEvent {
  text: string;
}

/** intent_plan 事件 */
interface SSEIntentPlanEvent {
  intents: IntentItem[];
}

/** data_card 事件（Phase 6 导出：推荐图表 + 表格 + 下载） */
interface SSEDataCardEvent extends DataCard {}

/** error 事件 */
interface SSEErrorEvent {
  error: string;
}
```

---

## 7. Vue 组件示例

### 7.1 流式对话组件（推荐）

使用 `fetch` + `ReadableStream` 处理 POST SSE（浏览器原生 `EventSource` 只支持 GET）。

```vue
<template>
  <div class="agent-chat">
    <!-- 意图计划展示 -->
    <div v-if="intentPlan.length" class="intent-plan">
      <div v-for="intent in intentPlan" :key="intent.id" class="intent-item">
        <span class="intent-badge">{{ categoryEmoji(intent.category) }}</span>
        {{ intent.description }}
        <span :class="intent.status">{{ intent.status }}</span>
      </div>
    </div>

    <!-- 流式报告展示 -->
    <div class="report" v-html="renderedReport"></div>

    <!-- 图表、表格与 CSV 必须共用 card.table.rows -->
    <div v-for="(card, i) in dataCards" :key="`card-${i}`" class="data-card">
      <h4>📊 {{ card.title }}</h4>
      <ChartRenderer
        v-if="card.chart"
        :spec="card.chart"
        :rows="card.table.rows"
      />
      <p v-if="card.chart" class="chart-reason">推荐理由：{{ card.chart.reason }}</p>
      <table>
        <thead>
          <tr>
            <th v-for="(col, j) in card.table.columns" :key="j">
              {{ col.label }}<span v-if="col.unit"> ({{ col.unit }})</span>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, r) in card.table.rows" :key="r">
            <td v-for="(col, c) in card.table.columns" :key="c">{{ row[col.key] }}</td>
          </tr>
        </tbody>
      </table>
      <a
        :href="`${API_BASE}${card.download.url}`"
        :download="card.download.filename"
        class="download-btn"
      >⬇️ 下载 CSV</a>
    </div>

    <!-- 导航动作 -->
    <div v-if="actions.length" class="actions">
      <button
        v-for="(action, i) in actions"
        :key="i"
        @click="handleAction(action)"
      >
        前往: {{ action.route }}
      </button>
    </div>

    <!-- 输入 -->
    <div class="input-area">
      <input
        v-model="userInput"
        @keyup.enter="sendMessage"
        :disabled="isStreaming"
        placeholder="输入问题..."
      />
      <button @click="sendMessage" :disabled="isStreaming || !userInput.trim()">
        {{ isStreaming ? '生成中...' : '发送' }}
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue';
import { useRouter } from 'vue-router';
import { marked } from 'marked';

const router = useRouter();

// ── 配置 ──────────────────────────────────────────
const API_BASE = import.meta.env.VITE_AGENT_API_URL || 'http://localhost:8000';
const API_KEY = import.meta.env.VITE_AGENT_API_KEY || '';

// ── 状态 ──────────────────────────────────────────
const userInput = ref('');
const report = ref('');
const intentPlan = ref<IntentItem[]>([]);
const actions = ref<UIAction[]>([]);
const dataCards = ref<DataCard[]>([]);
const isStreaming = ref(false);

const renderedReport = computed(() => marked(report.value));

// ── 页面上下文（根据当前路由动态构建） ──────────────
function getPageContext(): PageContext {
  return {
    current_route: router.currentRoute.value.path,
    site_id: 'FJJB000001', // 从全局状态或 store 获取
    params: router.currentRoute.value.params as Record<string, unknown>,
    meta: {},
  };
}

// ── 意图类别 emoji 映射 ────────────────────────────
function categoryEmoji(category: string): string {
  const map: Record<string, string> = {
    monitor: '📡',
    hvac: '❄️',
    energy: '⚡',
    alarm: '🚨',
    export: '📊',
    general: '💬',
  };
  return map[category] || '💬';
}

// ── 发送消息（SSE 流式） ──────────────────────────
async function sendMessage() {
  if (!userInput.value.trim() || isStreaming.value) return;

  const input = userInput.value.trim();
  userInput.value = '';
  report.value = '';
  intentPlan.value = [];
  actions.value = [];
  dataCards.value = [];
  isStreaming.value = true;

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  if (API_KEY) {
    headers['Authorization'] = `Bearer ${API_KEY}`;
  }

  try {
    const response = await fetch(`${API_BASE}/stream`, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        user_input: input,
        user_id: currentUserId, // 从现有登录态获取稳定用户 ID
        page_context: getPageContext(),
      }),
    });

    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${response.status}`);
    }

    const reader = response.body!.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // 按双换行分割 SSE 事件
      const events = buffer.split('\n\n');
      buffer = events.pop() || ''; // 最后一个可能不完整，保留

      for (const rawEvent of events) {
        if (!rawEvent.trim()) continue;

        const eventMatch = rawEvent.match(/^event: (\w+)/m);
        const dataMatch = rawEvent.match(/^data: (.+)$/m);

        if (!eventMatch || !dataMatch) continue;

        const eventType = eventMatch[1];
        const data = JSON.parse(dataMatch[1]);

        switch (eventType) {
          case 'thinking':
            // 思考过程（可选：折叠展示或丢弃）
            // thinkingText.value += data.text;
            break;
          case 'tool_call':
            // 工具调用（可选：展示调用过程）
            // toolCalls.value.push(data);
            break;
          case 'tool_result':
            // 工具结果（可选：展示原始数据）
            // toolResults.value.push(data);
            break;
          case 'rag_sources':
            // RAG 来源（可选：展示为引用）
            // ragSources.value = data;
            break;
          case 'text':
            // 最终回答（必须展示）
            report.value += data.text;
            break;
          case 'intent_plan':
            intentPlan.value = data.intents;
            break;
          case 'action':
            actions.value.push(data);
            break;
          case 'data_card':
            // 图表配置、表格与下载信息均包含在同一张 DataCard 中
            dataCards.value.push(data as DataCard);
            break;
          case 'error':
            console.error('[Agent Error]', data.error);
            report.value += `\n\n❌ **错误**: ${data.error}`;
            break;
          case 'done':
            // 流结束
            break;
        }
      }
    }
  } catch (error: unknown) {
    const msg = error instanceof Error ? error.message : '未知错误';
    report.value = `❌ 请求失败: ${msg}`;
  } finally {
    isStreaming.value = false;
  }
}

// ── 处理 UI 动作（页面跳转） ──────────────────────
function handleAction(action: UIAction) {
  if (action.type === 'navigate') {
    // 方式 1: Vue Router 内部跳转
    router.push({ path: action.route, query: action.params as Record<string, string> });

    // 方式 2: 如果是外部链接（福加平台路由），直接跳转
    // window.location.href = `https://aiot-fuca.com${action.route}`;
  }
}
</script>
```

### 7.2 同步调用（简单场景）

如果不需要流式效果，可使用 `/invoke`：

```typescript
async function invokeAgent(input: string): Promise<AgentInvokeResponse> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  if (API_KEY) {
    headers['Authorization'] = `Bearer ${API_KEY}`;
  }

  const res = await fetch(`${API_BASE}/invoke`, {
    method: 'POST',
    headers,
    body: JSON.stringify({
      user_input: input,
      page_context: {
        current_route: router.currentRoute.value.path,
        site_id: 'FJJB000001',
        params: {},
        meta: {},
      },
    }),
  });

  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || `HTTP ${res.status}`);
  }

  return res.json();
}
```

---

## 8. 页面跳转处理

Agent 返回的 `action` 中，`type: "navigate"` 表示建议前端跳转到某个页面。

### 8.1 UIAction 结构

```json
{
  "type": "navigate",
  "route": "/analysis/consumption-panel",
  "name": "能耗分析",
  "params": { "site_id": "FJJB000001", "date": "2026-06-17" },
  "meta": {}
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `type` | `string` | 动作类型，当前固定 `"navigate"` |
| `route` | `string` | 目标路由路径，始终以 `/` 开头 |
| `name` | `string` | 页面名称（如"能耗分析"、"设备运行"），可直接用于 UI 展示 |
| `params` | `object` | 路由参数（如 site_id, date） |
| `meta` | `object` | UI 元数据（预留扩展） |

> **提示**: `name` 字段由后端根据 `routes.yaml` 自动填充，前端可直接用于显示，无需自行维护路由→名称映射表。

### 8.2 前端处理策略

| 场景 | 处理方式 |
|------|----------|
| 内部路由 | `router.push({ path: action.route, query: action.params })` |
| 福加平台路由 | `window.location.href = \`https://aiot-fuca.com${action.route}\`` |
| 需要用户确认 | 渲染为可点击按钮，用户点击后执行跳转 |

### 8.3 已知路由列表

Agent 能识别的路由定义在 `config/routes.yaml` 中。前端无需关心路由是否合法——Agent 只会返回已注册的路由。

### 8.4 报表下载跳转（运维/用能报表）

用户问「运维报表」「用能报表」「下载报表」「报表管理」时，Agent **不调用数据查询工具**，直接通过 `action` 事件下发跳转到 `/report-center/manage`（报表管理页）。该页面是福加官网原生页面，含运维报表和用能报表列表，用户自行查看下载。

```
event: action
data: {"type": "navigate", "route": "/report-center/manage", "name": "报表管理", "params": {}, "meta": {}}
```

前端按标准 `action` 处理即可（见 §7、§8.2）。Agent 回答正文简短（如"已为您打开报表管理页面，可在该页面查看和下载运维报表、用能报表"），不返回具体报表数值。

> **与数据导出的区分**：用户要"把能耗/报警数据导出为 CSV 表格"走 `data_card` 事件（见 §11）；用户要"看运维/用能报表"走 `action` 跳转（本节），不导出。

### 8.5 光伏/冷负荷/电负荷预测跳转

用户问「光伏预测」「冷负荷预测」「电负荷预测」「预测准不准/平均偏差」「今日/昨日/上周预测对比」「光伏天气预报」「当前负荷/预测负荷」等预测对比类问题时，Agent 调用 `fetch_pv_forecast`（光伏，energyType=pv）/`fetch_load_forecast`（冷负荷，energyType=load）/`fetch_electricity_forecast`（电负荷，energyType=electricity）查询福加 loadForecast 真实数据后，通过 `action` 事件下发跳转：

- 光伏预测 → `/analysis/pv-forecast`（菜单：系统管理 → 光伏预测）
- 冷负荷预测 → `/analysis/load-forecast`（菜单：智能算法 → 负荷预测）
- 电负荷预测 → `/analysis/electricity-forecast`（菜单：智能算法 → 电负荷预测）

> **多意图双跳转（重要）**：用户泛问「负荷预测」「预测负荷」「当前负荷」「负荷平均偏差」等**未指明冷/电**时，Agent **同时调用 `fetch_load_forecast` 与 `fetch_electricity_forecast`**，在回答中分别给出冷负荷、电负荷两组预测值，并通过 `action` 事件下发**两个跳转**（`/analysis/load-forecast` + `/analysis/electricity-forecast`）。只有用户明确说「冷负荷」或「电负荷」时才只跳一个。

```
event: action
data: {"type": "navigate", "route": "/analysis/pv-forecast", "name": "光伏预测", "params": {}, "meta": {}}
```

回答正文用工具返回的**汇总指标**组织（不返回逐时原始点）：今日/昨日/上周的预测 vs 实际峰值功率与累计电量、平均偏差/准确率与评估等级、天气（日=逐时温湿度，周=每日最高/最低/湿度）；冷负荷额外带当前负荷/预测负荷/下小时预测。完整逐时曲线由预测页面可视化。

> **与「光伏发电量」的区分**：问"今天发了多少电/发电量/光伏收益"→ `fetch_photovoltaic_daily` 跳 `/coordination/energy`（光储实时能量）；问"预测对比/准确率/天气"→ `fetch_pv_forecast` 跳 `/analysis/pv-forecast`（本节）。两者页面与工具不同，Agent 按 prompt 规则区分。

---

## 9. 错误处理

### 9.1 HTTP 状态码

| 状态码 | 场景 | 前端处理 |
|--------|------|----------|
| 200 | 成功 | 正常渲染 |
| 401 | API Key 无效 | 提示用户联系管理员 |
| 422 | 请求参数错误 | 检查请求体格式 |
| 500 | Agent 执行失败 | 展示 `detail` 错误信息，允许用户重试 |

### 9.2 SSE 流中的错误

流式传输过程中可能出现 `error` 事件：

```
event: error
data: {"error": "Agent 执行超时"}
```

前端应捕获此事件并向用户展示错误信息。

### 9.3 网络错误

```typescript
try {
  const response = await fetch(`${API_BASE}/stream`, { ... });
} catch (error) {
  // 网络不可达、CORS 错误、DNS 解析失败等
  showToast('无法连接 AI 服务，请检查网络');
}
```

---

## 10. 常见问题

### Q: 为什么不用 EventSource？

浏览器原生 `EventSource` 只支持 GET 请求。我们的 `/stream` 需要 POST 发送请求体，因此使用 `fetch` + `ReadableStream` 方案。

### Q: 如何处理 Markdown 渲染？

报告是标准 Markdown 格式，推荐使用 `marked` 或 `markdown-it` 库渲染：

```bash
npm install marked
```

### Q: `page_context` 可以不传吗？

可以。但不传的话 Agent 无法感知用户当前所在页面，导航建议可能不够精准。建议始终传入。

### Q: 支持对话历史吗？

当前版本每次请求是独立的，不支持多轮对话。如需对话历史，需前端维护 `messages` 数组并在 `user_input` 中拼接上下文。后续版本会原生支持。

### Q: 如何区分"Agent 建议跳转"和"直接跳转"？

`action` 事件是 Agent 的**建议**，前端可以选择：
- **自动跳转**: 收到 action 后立即执行
- **用户确认**: 渲染为按钮，用户点击后执行（推荐）
- **忽略**: 仅展示报告，不处理 action

---

## 11. 数据导出对接（Phase 6）

> Phase 6 数据导出与自动图表已上线。本节是前端对接的单点说明。

### 11.1 能力概述

用户问「导出最近 7 天的能耗数据」→ Agent 查询多日数据，并用同一批 rows 生成推荐图表、表格和 CSV。时间趋势推荐折线图，分类比较推荐柱状图，明确构成语义推荐饼图；不适合绘图时 `chart=null`。

**统一导出模板原则（重要）**：导出能力是统一模板，`data_card` 事件 / `/export` 端点 / 前端渲染逻辑**全部复用**。后续新增可导出数据类型（光伏发电、光伏预测等）**前端零改动**——后端新增范围查询工具 + prompt 一行即可，前端自动渲染新表格。

**轻量协议约束**：后端仅输出 JSON 字段映射，不生成图片或完整 ECharts option。单图最多 4 个同单位系列；其他字段仍保留在表格和 CSV。Streamlit 渲染仅用于本地开发预览，生产前端统一使用 `ChartRenderer`。

### 11.2 端到端流程

```
用户输入「导出最近7天能耗数据」
        │
        ▼
POST /stream ──► Agent 识别导出意图
        │         ├─ 解析日期范围（最近7天 = 今天往前推6天，含今天）
        │         ├─ 调用 fetch_energy_range 取多日数据
        │         └─ 调用 export_data_table 生成 CSV + DataCard
        │
        ▼  SSE 事件流
  event: tool_call      (fetch_energy_range)
  event: tool_result
  event: tool_call      (export_data_table)
  event: tool_result
  event: data_card   ◄── 前端据此渲染图表 + 表格 + 下载按钮
  event: action         (跳转 /analysis/consumption-panel)
  event: text × N       (数据总结：总量/均值/峰值)
  event: done
        │
        ▼
前端渲染推荐图表 + 表格 + 「⬇️ 下载 CSV」按钮
        │ 用户点击
        ▼
GET /export/{task_id} ──► 返回 CSV（utf-8-sig BOM，Excel 直开）
```

### 11.3 `GET /export/{task_id}` 下载端点

| 项 | 说明 |
|----|------|
| 方法 | `GET` |
| 鉴权 | ❌ 不需要（`<a href>` 直接点击，无需 Bearer 头） |
| 路径参数 | `task_id` —— uuid hex（32 位十六进制），由 `data_card.download.task_id` 提供 |
| 成功响应 | `200`，`Content-Type: text/csv; charset=utf-8`，`Content-Disposition: attachment; filename="{task_id}.csv"` |
| 文件不存在/过期 | `404` —— 导出文件短期 ephemeral，过期后需重新触发导出 |
| 非法 task_id | `400` —— 含非 hex 字符（防路径穿越） |

```bash
# 测试下载
curl http://localhost:8000/export/{task_id} -o export.csv
# 文件首行（含 BOM ﻿ + 中文表头 + 单位）：
# ﻿日期,总用电量 (kWh),光伏发电 (kWh),电网取电 (kWh),...
```

> **task_id 安全性**：服务端用 hex 字符集 allowlist 校验（`[0-9a-f]`，排除 `/`、`.`、`\`），杜绝路径穿越。前端无需额外校验。

### 11.4 前端对接清单

| 对接项 | 说明 | 参考章节 |
|--------|------|----------|
| SSE `data_card` 事件处理 | 收到事件 push 到 `dataCards` 数组 | §5、§7 |
| 图表渲染 | 映射 line/bar/pie，所有值从 `table.rows` 读取 | §5、§6 |
| 表格渲染 | 按 `columns` 顺序渲染表头（`label` + 单位），行按 `key` 取值 | §7 |
| 下载按钮 | `<a :href="API_BASE + download.url" :download="download.filename">` | §7 |
| `/invoke` 同步响应 | 响应体新增 `data_cards` 字段（与 SSE `data_card` 同构） | §4 |
| TypeScript 类型 | `DataCard` / `TableData` / `ColumnDef` / `DownloadInfo` / `SSEDataCardEvent` | §6 |
| 过期容错 | `/export` 返回 404 时隐藏按钮或提示「文件已过期，请重新导出」 | §11.3 |

### 11.5 推荐测试用例

启动 Streamlit 演示前端（`conda run -n energraph streamlit run src/frontend/app.py`）或对接后调 `/stream`，用以下提示词测试（侧边栏「📊 数据导出测试」已内置）：

| # | 测试提示词 | 验收点 |
|---|-----------|--------|
| 1 | 导出最近 7 天的能耗数据 | 出现 `data_card` 事件；表格 7 行（含今天）；下载按钮可下载 CSV；正文有总量/均值总结；附带 `/analysis/consumption-panel` 跳转 |
| 2 | 导出最近 30 天能耗表格 | LLM 解析「30 天」=今天往前推 29 天；表格约 30 行 |
| 3 | 导出 6 月 20 日到 6 月 26 日的能耗数据 | LLM 解析指定日期范围；表格行数 = 日期跨度 |
| 4 | 导出本月报警记录 | 走 `fetch_alarm_history`；表格为报警明细（级别/设备/信息/时间）；附带 `/alarm/history` 跳转 |
| 5 | 查一下今天的能耗，并导出最近 7 天能耗表格 | 多意图：先回答今日能耗（`fetch_energy_summary`），再导出 7 天表格（`fetch_energy_range` + `export_data_table`） |
| 6 | 导出最近 7 天的光伏预测数据 | 走 `fetch_pv_forecast_range`；表格 7 行（今日行 accuracy 为数值、含 current_load_kw/next_hour_forecast_kw，其余行 accuracy 为「-」）；附带 `/analysis/pv-forecast` 跳转 |
| 7 | 导出最近 7 天的冷负荷预测数据 | 走 `fetch_load_forecast_range`；结构同上（energyType=load）；附带 `/analysis/load-forecast` 跳转 |
| 8 | 导出最近 7 天的电负荷预测数据 | 走 `fetch_electricity_forecast_range`；结构同上（energyType=electricity）；附带 `/analysis/electricity-forecast` 跳转 |
| 9 | 导出最近 7 天的负荷预测数据（未指明冷/电） | 多意图：同调 `fetch_load_forecast_range` + `fetch_electricity_forecast_range`，导出两份 CSV（title 注明冷/电），下发两个跳转（`/analysis/load-forecast` + `/analysis/electricity-forecast`） |
| 10 | 导出最近 7 天的 COP / 制冷量数据 | 走 `fetch_efficiency_calendar(mode=day)`；返回当月每天 days 数组，按 7 天范围筛选；表格 7 行（date/cop/cool_kwh/electricity_kwh）；附带 `/analysis/calendar` 跳转 |

**通用验收点**：
- 图表、表格与下载后的 CSV 数值完全一致；不适合绘图时仅显示表格与 CSV；
- CSV 用 Excel/Numbers 打开中文不乱码（utf-8-sig BOM）；
- 下载文件名有语义（如 `FJJB000001_近7天能耗_20260620_20260626.csv`）；
- 回答正文只给数据总结，**不写**「请点击下载」之类链接（下载按钮自动出现）；
- 无 API 配置时（`FUCA_API_BASE_URL` 未设）Agent 返回 error 而非假数据。

### 11.6 扩展新可导出数据类型（前端零改动）

后端新增可导出数据类型（如光伏发电、光伏预测）时，前端**无需任何改动**，流程：

1. 后端新增该数据的范围查询工具（如 `fetch_pv_forecast_range`）；
2. 后端在 `prompts/main_graph.yaml`「数据导出规则」段补一行映射；
3. Agent 自动用 `export_data_table` 生成 DataCard，走同一条 `data_card` SSE 事件 + `/export` 端点。

前端已有的 `data_card` 渲染逻辑会自动渲染推荐图表 + 表格 + 下载按钮。

### 11.7 当前已支持的数据类型

| 数据类型 | 范围查询工具 | 跳转路由 |
|----------|-------------|----------|
| 能耗多日汇总 | `fetch_energy_range`（逐日复用 `fetch_energy_summary`） | `/analysis/consumption-panel` |
| 历史报警明细 | `fetch_alarm_history`（`listHisAlarms` POST） | `/alarm/history` |
| 光伏预测多日汇总 | `fetch_pv_forecast_range`（逐日复用 loadForecast realTime/changeRealTime，energyType=pv） | `/analysis/pv-forecast` |
| 冷负荷预测多日汇总 | `fetch_load_forecast_range`（同上，energyType=load） | `/analysis/load-forecast` |
| 电负荷预测多日汇总 | `fetch_electricity_forecast_range`（同上，energyType=electricity） | `/analysis/electricity-forecast` |
| COP/制冷量/用电量多日 | `fetch_efficiency_calendar`（mode=day，当月每天 days 数组，按日期范围筛选） | `/analysis/calendar` |

> `DataCard.chart` 已支持折线图、柱状图和饼图。图表值始终读取 `DataCard.table.rows`。

### 11.8 ECharts 映射

前端不得为图表保存第二份业务数据。`ChartRenderer` 只接收 `card.chart` 和 `card.table.rows`：

```typescript
function toEChartsOption(chart: ChartSpec, rows: Record<string, unknown>[]) {
  const chartRows = [...rows];
  const valueKey = chart.series[0]?.key;
  if (chart.type === 'bar' && valueKey && chart.sort !== 'none') {
    chartRows.sort((a, b) => {
      const delta = Number(a[valueKey]) - Number(b[valueKey]);
      return chart.sort === 'desc' ? -delta : delta;
    });
  }
  const categories = chartRows.map(row => row[chart.x_axis.key]);

  if (chart.type === 'pie') {
    const valueKey = chart.series[0].key;
    return {
      tooltip: { trigger: 'item' },
      series: [{
        type: 'pie',
        data: chartRows.map(row => ({ name: row[chart.x_axis.key], value: row[valueKey] })),
      }],
    };
  }

  return {
    tooltip: { trigger: 'axis' },
    legend: { show: chart.show_legend },
    xAxis: {
      type: 'category',
      data: categories,
      name: chart.x_axis.label,
      axisLabel: { rotate: Math.abs(chart.x_label_angle) },
    },
    yAxis: { type: 'value' },
    series: chart.series.map(item => ({
      type: chart.type,
      name: item.label,
      label: { show: chart.show_values, position: 'top' },
      data: chartRows.map((row, index) => ({
        value: row[item.key],
        itemStyle: chart.highlight_top && index === 0 ? { color: '#F59E0B' } : undefined,
      })),
    })),
  };
}
```

兼容要求：`chart` 缺失或为 `null` 时跳过图表，仍正常渲染表格和 CSV 下载。

排名柱状图验收：`sort=desc` 时按首个 series 数值降序；`show_values=true` 显示柱顶数值；`highlight_top=true` 高亮排序后第一项；单系列 `show_legend=false`；`x_label_angle=-45` 对应 ECharts `axisLabel.rotate=45`。
