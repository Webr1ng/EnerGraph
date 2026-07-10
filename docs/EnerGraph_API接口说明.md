## EnerGraph Agent API 接口说明

> 服务地址：`http://192.168.128.15:8000`
> API 文档（Swagger）：`http://192.168.128.15:8000/docs`
> 版本：v0.3.0 | 协议：HTTP + JSON / SSE

---

### 基础信息

所有 POST 请求使用 `Content-Type: application/json`。API 支持可选的 Bearer Token 鉴权（当前为开发模式，未启用）。CORS 已全量开放。

### 公共请求体模型

#### ActionAgentInput

```json
{
  "user_input": "用户输入文本（必填）",
  "page_context": {
    "current_route": "/analysis/query",
    "site_id": "可选，当前选中站点 ID",
    "params": {},
    "meta": {}
  }
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| `user_input` | string | 是 | 用户自然语言输入 |
| `page_context` | object | 否 | 前端当前页面上下文，用于辅助 Agent 理解用户所处场景 |
| `page_context.current_route` | string | 否 | 当前页面路由，默认 `/` |
| `page_context.site_id` | string | 否 | 当前选中的站点 ID |
| `page_context.params` | object | 否 | 页面级运行时参数（筛选条件、选中设备等） |
| `page_context.meta` | object | 否 | 扩展元数据 |

---

### 1. GET /health — 健康检查

用于前端心跳检测或服务可用性判断。

**请求**：无需请求体。

**响应** `200 OK`：

```json
{
  "status": "ok"
}
```

**前端调用示例**：

```javascript
const res = await fetch('http://192.168.128.15:8000/health');
const data = await res.json();
// data.status === "ok"
```

---

### 2. POST /invoke — 同步调用（完整响应）

同步运行 Agent，等待完整 ReAct 循环结束后一次性返回 Markdown 报告和 UI 动作列表。适用于不需要流式展示的场景。

**请求体**：`ActionAgentInput`（见上表）

**响应** `200 OK`：

```json
{
  "report": "Markdown 格式的完整回答文本",
  "actions": [
    {
      "type": "navigate",
      "route": "/analysis/query",
      "name": "能效查询",
      "params": { "site_id": "SH-001" },
      "meta": {}
    }
  ]
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `report` | string | LLM 生成的 Markdown 格式完整报告 |
| `actions` | array | 待执行的 UI 动作列表（可能为空） |
| `actions[].type` | string | 动作类型：`navigate`（页面跳转）等 |
| `actions[].route` | string | 目标路由，始终以 `/` 开头 |
| `actions[].name` | string | 页面名称（如"能耗分析"、"设备运行"） |
| `actions[].params` | object | 路由参数（如 site_id、chiller_id） |
| `actions[].meta` | object | UI 元数据（面包屑、高亮目标等） |

**错误响应** `500`：Agent 执行失败。

**前端调用示例**：

```javascript
const res = await fetch('http://192.168.128.15:8000/invoke', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    user_input: '冷水机房的COP怎么样？',
    page_context: { current_route: '/dashboard' }
  })
});
const { report, actions } = await res.json();

// 渲染 Markdown 报告
renderMarkdown(report);

// 处理 UI 动作（如页面跳转）
if (actions.length > 0) {
  const nav = actions.find(a => a.type === 'navigate');
  if (nav) router.push(nav.route);
}
```

---

### 3. POST /stream — 流式调用（SSE，推荐）

以 Server-Sent Events 格式流式推送 Agent 执行过程中的细粒度事件。前端可逐步渲染回答，用户体验更佳。**生产环境推荐使用此接口。**

**请求体**：`ActionAgentInput`（同 /invoke）

**响应**：`Content-Type: text/event-stream`，逐条推送 SSE 事件。

#### SSE 事件类型一览

| 事件类型 | 触发时机 | 用途建议 |
|----------|----------|----------|
| `thinking` | Agent 思考阶段（工具调用前） | 可折叠展示或丢弃 |
| `tool_call` | Agent 调用工具（名称 + 参数） | 可折叠展示或丢弃 |
| `tool_result` | 工具返回结果 | 可折叠展示或丢弃 |
| `rag_sources` | RAG 知识库检索结果 | 可折叠展示来源引用 |
| `text` | 最终回答文本（逐 token 流式） | **主体内容，逐字渲染** |
| `intent_plan` | 多意图识别计划 | 展示意图拆分卡片 |
| `action` | 页面跳转等 UI 动作 | 触发前端路由跳转 |
| `error` | 执行出错 | 展示错误提示 |
| `done` | 流结束标志 | 停止 loading 状态 |

#### 各事件 data 格式

**thinking**：
```json
{ "text": "这是一个暖通空调专业问题，我来查询相关知识库。" }
```

**tool_call**：
```json
{ "name": "query_hvac_knowledge", "args": { "question": "冷水机组COP如何计算" } }
```

**tool_result**：
```json
{
  "name": "query_hvac_knowledge",
  "result": {
    "query": "冷水机组COP如何计算",
    "results": ["检索到的文档1", "文档2", "文档3"],
    "distances": [0.21, 0.22, 0.23],
    "low_confidence": false,
    "source_snippets": ["来源摘要1", "来源摘要2"]
  }
}
```

**rag_sources**（与 tool_result 中的 hvac_knowledge 数据相同）：
```json
{
  "query": "...",
  "results": ["..."],
  "distances": [0.15, 0.30],
  "low_confidence": false,
  "source_snippets": ["..."]
}
```

**text**：
```json
{ "text": "## 冷水机组COP的计算方法\n\n" }
```

**intent_plan**（多意图场景）：
```json
{
  "intents": [
    { "id": 0, "description": "查询冷水机房COP", "category": "monitor", "status": "pending" },
    { "id": 1, "description": "查看今日能耗", "category": "energy", "status": "pending" }
  ]
}
```

**action**：
```json
{ "type": "navigate", "route": "/analysis/query", "name": "能效查询", "params": {}, "meta": {} }
```

**error**：
```json
{ "error": "Agent 执行失败: ..." }
```

**done**：
```json
{}
```

#### 前端调用示例（推荐实现）

```javascript
async function streamAgent(userInput, pageContext) {
  const res = await fetch('http://192.168.128.15:8000/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_input: userInput, page_context: pageContext })
  });

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let answerText = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop(); // 保留未完成的行

    for (const line of lines) {
      if (line.startsWith('event: ')) {
        const eventType = line.slice(7).trim();
        // 下一行是 data
        continue;
      }
      if (line.startsWith('data: ')) {
        const data = JSON.parse(line.slice(6));
        handleSSEEvent(currentEventType, data);
      }
    }
  }

  function handleSSEEvent(type, data) {
    switch (type) {
      case 'text':
        // 逐字追加到回答区域
        answerText += data.text;
        renderMarkdown(answerText);
        break;
      case 'thinking':
        // 可选：展示思考过程（折叠面板）
        appendThinking(data.text);
        break;
      case 'tool_call':
        // 可选：展示工具调用状态
        showToolCall(data.name, data.args);
        break;
      case 'tool_result':
        // 可选：展示工具结果
        showToolResult(data.name, data.result);
        break;
      case 'rag_sources':
        // 可选：展示知识库来源
        showRAGSources(data);
        break;
      case 'intent_plan':
        // 多意图：展示意图拆分卡片
        showIntentPlan(data.intents);
        break;
      case 'action':
        // 执行 UI 动作（如页面跳转）
        if (data.type === 'navigate') {
          router.push(data.route);
        }
        break;
      case 'error':
        showError(data.error);
        break;
      case 'done':
        setLoading(false);
        break;
    }
  }
}

// 使用
streamAgent('冷水机房的COP怎么样？', { current_route: '/dashboard' });
```

#### 更简洁的 EventSource 替代方案

由于 `EventSource` 不支持 POST 请求和自定义 Headers，SSE 流式接口需使用 `fetch` + `ReadableStream` 方式（如上例）。如果需要更简单的实现，可使用第三方库如 `@microsoft/fetch-event-source`：

```javascript
import { fetchEventSource } from '@microsoft/fetch-event-source';

await fetchEventSource('http://192.168.128.15:8000/stream', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ user_input: '冷水机房COP多少？' }),
  onmessage(ev) {
    const data = JSON.parse(ev.data);
    if (ev.event === 'text') answerText += data.text;
    if (ev.event === 'done') setLoading(false);
  }
});
```

---

### 测试结果汇总

| 接口 | 方法 | 状态 | 测试内容 |
|------|------|:----:|----------|
| `/health` | GET | 通过 | 返回 `{"status":"ok"}` |
| `/invoke` | POST | 通过 | HVAC RAG 问答，返回完整 COP 计算报告 |
| `/stream` | POST | 通过 | SSE 事件链完整：thinking → tool_call → tool_result → rag_sources → text → done |
| `/knowledge/documents` | POST | 通过 | `multipart/form-data` 上传 doc/docx/txt/json/pdf 并自动入库 |
| `/knowledge/documents` | GET | 通过 | 查询上传文档及处理状态 |
| `/knowledge/documents/{document_id}` | GET / DELETE | 通过 | 查询详情；删除原文件、登记与全部向量 chunks |
| `/knowledge/documents/{document_id}/reprocess` | POST | 通过 | 从原文件重新解析并入库 |
| Streamlit Demo | — | 通过 | HTTP 200，`/_stcore/health` 返回 ok |

---

### 服务地址速查

| 服务 | 地址 |
|------|------|
| Agent API | `http://192.168.128.15:8000` |
| Swagger 文档 | `http://192.168.128.15:8000/docs` |
| Streamlit Demo | `http://192.168.128.15:8501` |
