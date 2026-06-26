# EnerGraph 记忆模块功能实现说明

> 本文基于 2026-06-25 周溥林在暂存区与未暂存区的 memory 相关实现整理，面向后续开发、联调、Code Review 与前端人工验证。规划背景见 `docs/plan_memory_module.md`，框架选型见 `docs/research_memory_frameworks.md`。

## 1. 基础定位

EnerGraph 记忆模块属于 **Agent 层基础设施**，不是算法模型层计算引擎，因此不强制通过 MCP 暴露。当前实现采用三层记忆架构：

| 层级 | 名称 | 当前实现 | 职责 |
|------|------|----------|------|
| L1 | 短期记忆 | LangGraph checkpointer：优先 `PostgresSaver`，失败/未启用回退 `MemorySaver` | 按 `thread_id` 保存多轮对话消息与 `AgentState` 快照 |
| L2 | 长期记忆 | `src/memory/store.py` 门面 + InMemory fallback + 可选 demo 文件落盘；PostgresStore 当前为探测占位 | 跨会话保存用户偏好、站点事实、决策历史、安全约束等语义记忆 |
| L3 | 知识检索 | 现有 ChromaDB HVAC RAG | 专业知识库检索，和“记忆”概念分离 |

关键约束：

- Agent 不在 Python 中实现能源计算，记忆模块只保存/检索上下文，不参与数值推导。
- L1 checkpoint 与 L2 长期记忆共用一个 PostgreSQL 实例，避免 Redis/Milvus/Neo4j/ES 多件套。
- L2 默认按 `namespace_prefix/env/site_id/agent_id/scope/entity_id` 隔离。
- 写入长期记忆必须经过 `MemoryWrite` / `MemoryStore.save()` 门面；当前支持关键词 fallback 与可配置 LLM 结构化自动抽取双路径。
- Tool I/O 使用 Pydantic 模型，异常统一返回 `{"error": "memory: ..."}`，不得让 Agent 主流程崩溃。

## 2. 相关文件

| 文件 | 作用 |
|------|------|
| `src/config/settings.py` | `MemoryConfig` 与环境变量覆盖 |
| `src/graph/builder.py` | 构建 checkpointer、编译 LangGraph、生成 `thread_id` config |
| `src/graph/state.py` | `AgentState` 增加 `thread_id/agent_id/site_id/memory_*` 字段 |
| `src/graph/nodes.py` | 入口 L2 记忆注入、出口 `memory_manager_node` 按需写入 |
| `src/memory/extractor.py` | LLM 结构化抽取与 JSON 解析，不直接写库 |
| `src/memory/store.py` | L2 长期记忆客户端门面、namespace、TTL、demo 文件落盘 |
| `src/schemas/memory.py` | `MemoryQuery/MemoryWrite/MemoryItem/*Result`、`MemoryCandidate/MemoryExtractionResult` 等模型 |
| `src/tools/memory_ops.py` | `search_memory` / `search_relevant_memory` / `save_memory` Tool 实现 |
| `src/tools/__init__.py` | 注册 memory Tools 与 function calling schema |
| `src/services/api.py` | `/invoke`、`/stream` 支持可选 `thread_id` |
| `src/frontend/app.py` | Streamlit 会话生成稳定 `thread_id` |
| `src/tests/test_memory_*.py` | store、tool、namespace 隔离、demo 文件落盘测试 |

## 3. 配置项

默认配置位于 `config/agent_config.yaml`，生产/联调时优先使用 `.env` 覆盖：

```ini
MEMORY_ENABLED=false
MEMORY_POSTGRES_DSN=postgresql://energraph:energraph@localhost:5432/energraph
LANGGRAPH_STRICT_MSGPACK=true
CHECKPOINT_TABLE=checkpoints
STORE_TABLE=store
MEMORY_NAMESPACE_PREFIX=energraph
MEMORY_ENV=dev
MEMORY_DEFAULT_SITE_ID=local
MEMORY_DEFAULT_AGENT_ID=main_graph
MEMORY_DEFAULT_TTL_SECONDS=0
MEMORY_AUTO_EXTRACT_ENABLED=false
MEMORY_EXTRACT_MIN_CONFIDENCE=0.65
MEMORY_MAX_MEMORIES_PER_TURN=3
MEMORY_DEVICE_STATE_DEFAULT_TTL_SECONDS=86400
MEMORY_USE_POSTGRES_STORE=false
MEMORY_DEMO_FILE_STORE_ENABLED=false
MEMORY_DEMO_FILE_STORE_PATH=data/long_term_memory_demo/memories.json
```

说明：

- `MEMORY_ENABLED=true` 时，主图会尝试启用 `PostgresSaver` 并执行 `.setup()`；本地未部署 PostgreSQL 时会回退内存 checkpoint。
- `LANGGRAPH_STRICT_MSGPACK=true` 会设置 LangGraph 安全反序列化开关。
- `MEMORY_USE_POSTGRES_STORE=false` 是当前推荐值；L2 生产级 PostgresStore 还未完成初始化接入。
- `MEMORY_AUTO_EXTRACT_ENABLED=false` 时保留旧关键词规则；设为 `true` 后启用 LLM 结构化抽取、质量闸门、按类型 scope/entity 写入。
- `MEMORY_EXTRACT_MIN_CONFIDENCE` 控制自动抽取最低写入置信度，默认 `0.65`。
- `MEMORY_MAX_MEMORIES_PER_TURN` 控制单轮最多写入数量，默认 `3`。
- `MEMORY_DEVICE_STATE_DEFAULT_TTL_SECONDS` 用于 `device_state` 候选缺 TTL 时自动补齐，默认 `86400` 秒。
- `MEMORY_DEMO_FILE_STORE_ENABLED=true` 只用于本地人工测试，把 InMemory fallback 同步到 `data/long_term_memory_demo/memories.json`，不替代生产级持久化。

当前仓库不再内置 `docker-compose.yml`。本地联调优先使用 `MEMORY_DEMO_FILE_STORE_ENABLED=true` 的 demo 文件落盘；如需验证生产级 Postgres checkpoint/store，请由运维或开发者自行提供 PostgreSQL + pgvector，并把 `MEMORY_POSTGRES_DSN` 指向该实例。

## 4. L1 Checkpoint 实现

`src/graph/builder.py` 在编译主图时构造 checkpointer。核心逻辑：

```python
def _build_checkpointer() -> Optional[Any]:
    if settings.memory.strict_msgpack:
        os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")

    if settings.memory.enabled:
        try:
            import psycopg
            from psycopg.rows import dict_row
            from langgraph.checkpoint.postgres import PostgresSaver

            conn = psycopg.connect(settings.memory.postgres_dsn, autocommit=True, row_factory=dict_row)
            checkpointer = PostgresSaver(conn)
            checkpointer.setup()
            return checkpointer
        except Exception:
            ...

    from langgraph.checkpoint.memory import MemorySaver
    return MemorySaver()
```

调用 graph 时必须传入 LangGraph config，否则启用 checkpointer 后会报缺少 `thread_id`：

```python
run_config = build_graph_config(input_data.thread_id)
thread_id = run_config["configurable"]["thread_id"]
result = graph.invoke({"user_input": text, "thread_id": thread_id}, config=run_config)
```

`build_graph_config()` 会在未传入 `thread_id` 时生成 `thread-<uuid>`，避免不同请求共用 checkpoint。

## 5. 多轮消息追加修复

checkpoint 恢复后，`messages` 已经带有历史消息。当前实现会区分两种情况：

- 新用户轮：追加本轮 `HumanMessage(user_input)`。
- 工具回环：最后一条是 `ToolMessage` 时不重复追加用户消息。

关键片段：

```python
last_message = messages[-1] if messages else None
is_tool_loop = isinstance(last_message, ToolMessage)
is_same_pending_user = (
    isinstance(last_message, HumanMessage)
    and str(last_message.content).strip() == user_input
)
if user_input and not is_tool_loop and not is_same_pending_user:
    messages.append(HumanMessage(content=state.get("user_input", "")))
```

这个修复解决了同一 `thread_id` 下多轮提问仍处理上一轮输入的问题。

## 6. L2 长期记忆模型

`src/schemas/memory.py` 定义了记忆类型与元数据：

```python
MemoryType = Literal[
    "user_preference",
    "site_fact",
    "decision_history",
    "device_state",
    "safety_constraint",
    "session_note",
]
```

`MemoryMetadata` 关键字段：

| 字段 | 说明 |
|------|------|
| `memory_type` | 记忆类型 |
| `source_thread_id` | 来源会话 ID |
| `site_id` | 站点 ID |
| `agent_id` | 写入 Agent |
| `confidence` | 置信度，0-1 |
| `valid_until` | 绝对有效期 |
| `ttl_seconds` | 相对 TTL |
| `tags` | 检索标签 |

自动抽取模型：

| 模型 | 说明 |
|------|------|
| `MemoryCandidate` | 单条候选，包含 `should_save/content/memory_type/confidence/ttl_seconds/tags/reason` |
| `MemoryExtractionResult` | 单轮抽取结果，包含 `candidates` 与可选 `skip_reason` |

注意事项：

- 只有 `device_state` 属于临时记忆，必须带 `valid_until` 或 `ttl_seconds`。
- `decision_history` 是已确认决策摘要，默认作为长期历史事实保存，不强制 TTL。
- `ttl_seconds` 会在创建 `MemoryItem` 时转换为 `valid_until`。
- 默认检索不返回过期记忆，除非 `include_expired=True`。

## 7. Namespace 隔离

多智能体记忆采用“物理共享、逻辑隔离、少量显式共享”的策略：

```text
同一个 PostgreSQL / LangGraph Store
  ├─ env
  ├─ site_id
  ├─ agent_id
  └─ memory_type
```

默认 namespace 构成为：

```python
[
    settings.memory.namespace_prefix,
    settings.memory.env,
    site_id or settings.memory.default_site_id,
    agent_id or settings.memory.default_agent_id,
    scope or "session_note",
    entity_id or "default",
]
```

示例：

```text
energraph/dev/FJJB000001/powerai/session_note/thread-1
energraph/prod/jiangbei_factory/powerai/site/FJJB000001
energraph/prod/jiangbei_factory/hvac_expert/site/FJJB000001
energraph/prod/jiangbei_factory/ui_router/user_preference/user_001
energraph/prod/jiangbei_factory/global/safety_constraint/FJJB000001
```

隔离规则：

- 不同 `env` 默认不互通，避免 dev/prod 混读。
- 不同 `site_id` 默认不互通，避免跨站点污染。
- 不同 `agent_id` 默认不互通，避免 HVAC 专家记忆被 PowerAI 直接读取。
- 跨 Agent 或跨 scope 读取必须显式传 `namespace`，Code Review 时要重点看是否有业务授权理由。

`BaseAgent.memory_namespace()` 为子 Agent 提供同样的默认构造方式。

### 7.1 共享 namespace 规则

为站点稳定事实和通用偏好预留 `global` / `site` 共享 namespace。推荐形态：

```text
prod / jiangbei_factory / global
```

可共享的记忆：

- 站点稳定事实：厂区名称、设备配置、建筑结构
- 用户通用偏好：报告先给结论、用中文、偏好表格
- 企业级安全红线：SOC 不低于 20%、禁止越过某些运行边界
- 已确认的长期业务约束

不应默认共享的记忆：

- `device_state`：当前设备状态、告警、瞬时功率，必须 TTL，过期不得使用
- `decision_history`：某个 Agent 的历史决策，只能作为该 Agent 的上下文
- PowerAI 调度策略细节，不应自动进入 HVAC 专家判断
- UI Router 页面操作上下文，不应污染业务判断

推荐检索顺序：

```text
1. global/site 共享记忆
2. 当前 agent_id 专属记忆
```

写入时默认写入当前 Agent 专属 namespace；只有明确属于站点事实、安全约束、用户长期偏好时，才写入共享 namespace。

## 8. L2 Store 当前能力

`MemoryStore` 是 Tool 层唯一应调用的长期记忆门面。当前能力包括：

- 单例管理：`get_memory_store()`。
- 写入：`save(MemoryWrite)`。
- 检索：`search(MemoryQuery)`。
- TTL 过滤：默认过滤过期记忆。
- 简单相关度：正文包含 query 时在 `confidence` 基础上加分。
- InMemory fallback：当前主要运行路径。
- demo 文件落盘：开启后加载/写入 `memories.json`。
- PostgresStore 探测：发现适配器但当前构建不初始化，返回明确 error。

demo 文件结构：

```json
{
  "schema_version": 1,
  "description": "EnerGraph demo L2 long-term memory fallback; not for production.",
  "items": []
}
```

## 9. Tool 实现

三个 Tool 位于 `src/tools/memory_ops.py`，并注册到 `TOOL_REGISTRY` 与 `TOOL_SCHEMAS`：

```python
def search_memory(...):
    try:
        request = MemoryQuery(...)
        result = get_memory_store().search(request)
        return _dump_model(result)
    except ValidationError as exc:
        return {"error": f"memory: {exc}"}
    except Exception as exc:
        return {"error": f"memory: {exc}"}
```

`search_memory` 保留显式 `scope/entity_id/namespace` 检索能力，适合精确读取某个记忆域；用户概括询问“你知道/你记得/长期信息/运行约束/站点事实/设备状态”等场景，应优先使用聚合检索工具：

```python
def search_relevant_memory(...):
    result = search_relevant_memories(
        query=query,
        agent_id=agent_id,
        site_id=site_id,
        thread_id=thread_id,
        limit=limit,
        include_expired=include_expired,
    )
```

```python
def save_memory(content: str, ..., metadata: Optional[Dict[str, Any]] = None):
    try:
        memory_metadata = coerce_metadata(metadata, agent_id=agent_id, site_id=site_id)
        request = MemoryWrite(content=content, metadata=memory_metadata, ...)
        result = get_memory_store().save(request)
        return _dump_model(result)
    except ValidationError as exc:
        return {"error": f"memory: {exc}"}
```

示例调用：

```python
save_memory(
    content="用户偏好报告先给结论，再给数据依据",
    agent_id="main_graph",
    site_id="FJJB000001",
    metadata={
        "memory_type": "user_preference",
        "source_thread_id": "thread-1",
        "confidence": 0.85,
        "tags": ["report_style"],
    },
)
```

```python
search_memory(
    query="报告格式",
    agent_id="main_graph",
    site_id="FJJB000001",
    limit=5,
)
```

```python
search_relevant_memory(
    query="江北工厂有哪些长期信息和运行约束",
    agent_id="main_graph",
    site_id="FJJB000001",
    thread_id="thread-1",
)
```

## 10. Graph 接入流程

主图新增 `memory_manager` 节点：

```text
cognitive_parser
  -> v3_engine_router -> cognitive_parser
  -> interpreter_generator
  -> memory_manager
  -> END
```

入口检索注入：

1. `cognitive_parser_node` 首轮构造 system prompt。
2. 读取 `site_id/agent_id/thread_id`。
3. 调用 `search_relevant_memories()`，按当前上下文同时检索：
   - `user_preference / entity_id=thread_id`
   - `site / entity_id=site_id`
   - `safety_constraint / entity_id=site_id`
   - `decision_history / entity_id=thread_id`
   - `device_state / entity_id=site_id`
   - 兼容旧数据：`session_note / entity_id=thread_id`
4. 聚合结果默认过滤过期 `device_state`，按 `memory.id` 或 `content` 去重，最多注入 10 条。
5. 检索结果经 `format_memories_for_prompt()` 格式化。
6. 注入 `memory_injection_hint` 与“用户历史偏好与长期记忆”。

出口写入：

1. `memory_manager_node` 只在 `MEMORY_ENABLED=true` 时运行。
2. `MEMORY_AUTO_EXTRACT_ENABLED=false` 时保留旧关键词规则：用户输入包含 `记住/偏好/以后/下次/默认` 时写入一条 `user_preference` demo 记忆。
3. `MEMORY_AUTO_EXTRACT_ENABLED=true` 时调用 `src/memory/extractor.py::extract_memories_from_turn()`，要求 LLM 返回 `MemoryExtractionResult` JSON。
4. 写入前执行质量闸门：跳过 `should_save=false`、低置信度、空/过短正文、无法补 TTL 的 `device_state`、超过单轮上限、完全重复正文。
5. `device_state` 候选缺 `ttl_seconds` 时，由代码层补 `MEMORY_DEVICE_STATE_DEFAULT_TTL_SECONDS`。
6. 写入失败只记录 `memory_write_result.error`，不阻断最终回答。

自动抽取 scope/entity 建议已落地：

| memory_type | scope | entity_id |
|-------------|-------|-----------|
| `user_preference` | `user_preference` | 暂用 `thread_id`，后续接真实 `user_id` |
| `site_fact` | `site` | `site_id` |
| `safety_constraint` | `safety_constraint` | `site_id` |
| `decision_history` | `decision_history` | `thread_id` |
| `device_state` | `device_state` | `site_id` |

当前抽取器底层直接调用项目 LLM provider；后续可把 `extract_memories_from_turn()` 内部替换为 LangMem，但仍不把 LangMem `manage_memory` tool 暴露给主 Agent。

## 11. API 与前端使用

`ActionAgentInput` 新增：

```python
thread_id: Optional[str] = Field(default=None, description="会话线程 ID，用于 LangGraph checkpoint 隔离")
```

HTTP 同步接口返回：

```json
{
  "report": "...",
  "actions": [],
  "thread_id": "thread-..."
}
```

前端联调建议：

- 同一聊天窗口持续传同一个 `thread_id`，才能恢复 L1 多轮上下文。
- 新建会话或清空对话时生成新的 `thread_id`。
- 每次请求尽量传 `page_context.site_id`，否则记忆会落到 `local` 站点 namespace。
- Streamlit 当前在 `st.session_state.thread_id` 中生成稳定 ID，并传入 `graph.stream(..., config=build_graph_config(...))`。

### Streamlit 人工测试启动方式

测试记忆自动抽取 + demo 文件落盘时，打开 Streamlit 前必须同时启用以下 3 个环境变量：

```bash
export MEMORY_ENABLED=true
export MEMORY_AUTO_EXTRACT_ENABLED=true
export MEMORY_DEMO_FILE_STORE_ENABLED=true
streamlit run src/frontend/app.py
```

也可以用一行命令临时启动：

```bash
MEMORY_ENABLED=true MEMORY_AUTO_EXTRACT_ENABLED=true MEMORY_DEMO_FILE_STORE_ENABLED=true streamlit run src/frontend/app.py
```

这三个开关的含义：

| 变量 | 必须开启的原因 |
|------|----------------|
| `MEMORY_ENABLED=true` | 启用 L1 checkpoint 与 L2 记忆注入/写入链路 |
| `MEMORY_AUTO_EXTRACT_ENABLED=true` | 启用 LLM 结构化自动抽取，否则只走关键词 fallback |
| `MEMORY_DEMO_FILE_STORE_ENABLED=true` | 将 InMemory fallback 同步到 `data/long_term_memory_demo/memories.json`，便于重启后复查写入结果 |

人工验收建议：

1. 第一轮输入：`我们江北工厂有一台磁悬浮主机；储能运行安全边界是 SOC 不得低于 20%；本次调度采用稳健型方案 A；现在 2 号冷却塔处于停机状态。`
2. 第二轮输入：`你知道江北工厂有哪些长期信息和运行约束吗？`
3. 预期回答应能基于 L2 聚合检索提到磁悬浮主机、SOC 安全边界、方案 A、2 号冷却塔状态。

## 12. 测试覆盖

当前新增/修改的关键测试：

| 测试 | 覆盖点 |
|------|--------|
| `test_memory_store.py` | 写入检索、TTL 过滤、临时记忆校验、非法 namespace、demo 文件落盘 |
| `test_memory_tools.py` | Tool 成功路径、非法临时记忆、limit 校验 |
| `test_memory_isolation.py` | env/site/agent namespace 隔离、BaseAgent namespace |
| `test_memory_extraction.py` | fake extractor 覆盖五类记忆写入、TTL 自动补齐、低置信度/闲聊过滤、单轮上限、写入失败兜底、legacy fallback、重复正文过滤 |
| `test_memory_relevant_search.py` | 聚合检索跨 scope 读取、过期 device_state 过滤、旧 session_note 兼容、site 隔离、入口注入回归 |
| `test_multi_intent.py` | checkpoint 恢复后追加新用户轮、工具回环不重复追加 |
| `test_action_agent.py` | API 传递/返回 `thread_id` 与 SSE mock 兼容 |

2026-06-25 已记录的验证结果包括：

- 记忆基础实现：`75 passed / 6 skipped`
- checkpoint config 修复后：`76 passed / 6 skipped`
- 多轮消息追加修复：相关回归 `28 passed`
- demo 文件落盘后：`79 passed / 6 skipped`
- 自动抽取 + 聚合检索后：`98 passed / 6 skipped`

## 13. 注意事项与待办

上线/联调前重点检查：

- `MEMORY_ENABLED=true` 后必须保证每次 graph 调用都带 `config={"configurable": {"thread_id": ...}}`。
- `PostgresSaver.setup()` 首次启用必须执行，否则 checkpoint 表不存在。
- `psycopg[binary,pool]` 不能退化成裸 `psycopg`，否则可能缺 `libpq`。
- demo 文件落盘只允许用于演示测试，生产不得依赖 `data/long_term_memory_demo/memories.json`。
- 临时设备状态、告警快照、单次调度决策必须设置 TTL。
- 已确认决策摘要应归为 `decision_history` 长期保存；临时策略建议或实时状态应归为 `device_state` 并带 TTL。
- 跨 Agent 读取需要显式 namespace，默认不互通。
- 记忆正文应保存稳定事实或偏好，不保存敏感凭据、API Token、未确认算法结论。
- 当前 L2 PostgresStore 尚未真正初始化，`MEMORY_USE_POSTGRES_STORE=true` 会得到明确 error；下一步需要在真实 PostgreSQL 上完成 PostgresStore/AsyncPostgresStore 接入与 LangMem 提取质量验收。

建议下一步：

1. 在真实 PostgreSQL 上验收 L1 同 `thread_id` checkpoint 恢复。
2. 完成 L2 `PostgresStore` 初始化、索引与迁移策略。
3. 用真实业务回放评估 `MEMORY_AUTO_EXTRACT_ENABLED=true` 的抽取质量，沉淀误写/漏写样例。
4. 后续用 LangMem 替换抽取器底层，并补充 update/delete 或向量相似去重能力。
5. 为前端确认 `thread_id` 生命周期：新会话、刷新页面、切换站点、登出时分别如何处理。
