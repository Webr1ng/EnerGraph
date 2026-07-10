"""FastAPI 服务层 — Action Agent HTTP API

所属层：services
依赖：fastapi, uvicorn, src.graph.builder, src.schemas, src.config.settings
对接算法层：N/A（通过 Graph 间接调用 Tools）
"""
import asyncio
import json
import logging
import re
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, List

from fastapi import Depends, FastAPI, HTTPException, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from langchain_core.messages import AIMessageChunk, ToolMessage

from src.config.settings import settings
from src.graph.builder import build_graph_config, get_async_graph, graph
from src.graph.nodes import is_explicit_memory_write_request
from src.schemas.action_agent import ActionAgentInput, UIAction
from src.schemas.v3_engine import IntentItem

logger = logging.getLogger(__name__)

# Phase 6 导出文件落盘目录（与 src/tools/export_data.py 同路径，data/ 已 gitignore）
_EXPORT_DIR = Path(__file__).resolve().parents[2] / "data" / "exports"
_STREAM_SEMAPHORE: asyncio.Semaphore | None = (
    asyncio.Semaphore(settings.api.max_concurrent_streams)
    if settings.api.max_concurrent_streams > 0
    else None
)


async def _prewarm_worker_dependencies() -> None:
    """在每个 API Worker 接流量前预热进程内 RAG 依赖。"""
    if not settings.rag.prewarm_on_startup:
        return
    from src.tools.query_hvac_knowledge import prewarm_hvac_knowledge

    result = prewarm_hvac_knowledge()
    if result.get("error"):
        logger.warning("HVAC RAG Worker 预热失败: %s", result["error"])
    else:
        logger.info("HVAC RAG Worker 预热完成: %s", result)


async def _acquire_stream_slot() -> bool:
    """尝试获取当前 Worker 的 /stream 执行槽。"""
    if _STREAM_SEMAPHORE is None:
        return True
    try:
        await asyncio.wait_for(
            _STREAM_SEMAPHORE.acquire(),
            timeout=settings.api.stream_queue_timeout_seconds,
        )
        return True
    except asyncio.TimeoutError:
        return False


async def _get_stream_graph():
    """按持久化能力选择 /stream 使用的图实例。

    启用 PostgreSQL checkpoint 时，``astream_events`` 必须搭配
    ``AsyncPostgresSaver``；未启用记忆的本地开发和测试继续复用同步图，
    保持轻量且兼容既有 Mock。

    Returns:
        可调用 ``astream_events`` 的编译图实例。
    """
    if settings.memory.enabled:
        return await get_async_graph()
    return graph


def _release_stream_slot(acquired: bool) -> None:
    """释放当前 Worker 的 /stream 执行槽。"""
    if acquired and _STREAM_SEMAPHORE is not None:
        _STREAM_SEMAPHORE.release()


@asynccontextmanager
async def _app_lifespan(_app: FastAPI):
    """管理单个 Worker 的启动预热生命周期。"""
    await _prewarm_worker_dependencies()
    yield

app = FastAPI(
    title="EnerGraph Action Agent",
    description="青山 V3 多模态调度 Agent HTTP API",
    version="0.3.0",
    lifespan=_app_lifespan,
)

# ── CORS 中间件 ──────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.api.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



# ── 鉴权（可选） ─────────────────────────────────────────────────
_security = HTTPBearer(auto_error=False)


async def _verify_api_key(
    credentials: HTTPAuthorizationCredentials = Security(_security),
) -> None:
    """Bearer Token 鉴权。api_key 为空时跳过（开发模式）。

    Raises:
        HTTPException: 401 — 密钥不匹配
    """
    expected = settings.api.api_key
    if not expected:
        return  # 开发模式，不鉴权
    if credentials is None or not secrets.compare_digest(credentials.credentials, expected):
        raise HTTPException(status_code=401, detail="无效的 API Key")


@app.get("/health")
async def health() -> dict:
    """健康检查端点。

    Returns:
        包含 status 字段的状态字典
    """
    return {"status": "ok"}


@app.get("/export/{task_id}")
async def download_export(task_id: str) -> FileResponse:
    """下载导出的 CSV 文件（Phase 6 数据导出）。

    task_id 由 export_data_table 工具生成（uuid4 hex），对应 data/exports/{task_id}.csv。
    不鉴权：task_id 不可猜、文件短期 ephemeral，下载链接需支持 ``<a href>`` 直接点击。

    Args:
        task_id: 导出任务 ID（uuid4 hex）

    Returns:
        FileResponse（text/csv，含 Content-Disposition 文件名）

    Raises:
        HTTPException: 400 非法 task_id；404 文件不存在/已过期
    """
    # 仅允许 uuid hex，防止路径穿越
    if not task_id or not all(c in "0123456789abcdef" for c in task_id):
        raise HTTPException(status_code=400, detail="非法 task_id")
    file_path = _EXPORT_DIR / f"{task_id}.csv"
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="导出文件不存在或已过期")
    return FileResponse(
        path=str(file_path),
        media_type="text/csv",
        filename=f"{task_id}.csv",
    )


@app.post("/invoke")
async def invoke(
    input_data: ActionAgentInput,
    _: None = Depends(_verify_api_key),
) -> JSONResponse:
    """同步运行 Agent，返回最终报告和 UI 动作列表。

    接收用户输入和可选页面上下文，经过完整的 ReAct 循环后，
    返回 LLM 生成的 Markdown 报告和所有待执行的 UI 动作。

    Args:
        input_data: 包含 user_input 和可选 page_context 的请求体

    Returns:
        JSONResponse，body 含 report(str) 和 actions(List[dict])

    Raises:
        HTTPException: Agent 执行失败时返回 500
    """
    run_config = build_graph_config(input_data.thread_id)
    thread_id = run_config["configurable"]["thread_id"]
    initial_state: dict = {"user_input": input_data.user_input, "thread_id": thread_id}
    if input_data.user_id:
        initial_state["user_id"] = input_data.user_id
    if input_data.page_context is not None:
        initial_state["page_context"] = input_data.page_context
        if input_data.page_context.site_id is not None:
            initial_state["site_id"] = input_data.page_context.site_id

    try:
        result = graph.invoke(initial_state, config=run_config)
    except Exception as e:
        logger.error(f"Agent 调用失败: {e}")
        raise HTTPException(status_code=500, detail=f"Agent 执行失败: {e}")

    error = result.get("error")
    if error:
        raise HTTPException(status_code=500, detail=str(error))

    report: str = result.get("final_report", "")
    pending_actions: List[UIAction] = result.get("pending_actions", [])

    actions_dicts = []
    for action in pending_actions:
        if isinstance(action, UIAction):
            actions_dicts.append(action.model_dump())
        elif isinstance(action, dict):
            actions_dicts.append(action)
        else:
            actions_dicts.append(str(action))

    # Phase 6 导出数据卡片
    pending_data_cards = result.get("pending_data_cards", [])
    data_cards_dicts = [
        card.model_dump() if hasattr(card, "model_dump") else card
        for card in pending_data_cards
    ]

    return JSONResponse(content={
        "report": report,
        "actions": actions_dicts,
        "data_cards": data_cards_dicts,
        "thread_id": thread_id,
    })


class _StreamingTextSanitizer:
    """流式文本清理器：逐 chunk 实时输出，跨 chunk 尾部预留缓冲防漏网。

    每个 chunk 到达后立即做正则清理，但最后 15 字保留不发出（等待下一个 chunk
    确认不含跨 chunk 违禁模式），下次 chunk 到达时拼接后再清理、再发出。

    延迟：约 15 中文字符（2-3 词）≈ 不可感知。
    """

    _PENDING = 10  # 尾部保留字数（足以覆盖最长的违禁前缀 "已为您跳转到"=7字）

    _STRIP_DEL = re.compile(r"~~[^~]+~~")
    _FIX_TILDE = re.compile(r"(\d)\s*~\s*(\d)")
    _FORBIDDEN = re.compile(
        r"已为您跳转(?:至|到)?[^。\n]{0,30}[。]?"
        r"|已为您打开[^。\n]{0,30}[。]?"
        r"|已进入[^。\n]{0,30}页面[^。\n]{0,10}[。]?"
        r"|已切换到[^。\n]{0,30}[。]?"
    )
    _BLANKS = re.compile(r"\n{3,}")

    def __init__(self):
        self._buf = ""

    @classmethod
    def _clean(cls, text: str) -> str:
        text = cls._STRIP_DEL.sub("", text)
        text = cls._FIX_TILDE.sub(r"\1至\2", text)
        text = cls._FORBIDDEN.sub("", text)
        text = cls._BLANKS.sub("\n\n", text)
        return text

    def feed(self, chunk: str) -> str:
        """送入一个文本 chunk，返回可立即发出的安全文本。"""
        if not chunk:
            return ""
        self._buf += chunk
        self._buf = self._clean(self._buf)
        if len(self._buf) <= self._PENDING:
            return ""
        split = len(self._buf) - self._PENDING
        result = self._buf[:split]
        self._buf = self._buf[split:]
        return result

    def flush(self) -> str:
        """流结束时清洗并返回尾部缓冲。"""
        result = self._clean(self._buf).strip()
        self._buf = ""
        return result


async def _sse_generator(input_data: ActionAgentInput) -> AsyncIterator[str]:
    """SSE 流式推送生成器：按节点区分事件类型，推送细粒度 SSE 事件。

    事件类型：
    - thinking: cognitive_parser 的思考文本（流式）
    - tool_call: 工具调用（name + args）
    - tool_result: 工具返回结果（name + result）
    - rag_sources: RAG 知识库检索结果
    - text: interpreter_generator 的最终回答（流式）
    - intent_plan: 多意图识别计划
    - action: 页面跳转动作
    - data_card: 数据卡片（表格 + 下载按钮，Phase 6 导出）
    - error: 错误
    - done: 流结束

    Args:
        input_data: 包含 user_input 和可选 page_context 的请求体

    Yields:
        SSE 格式字符串
    """
    run_config = build_graph_config(input_data.thread_id)
    thread_id = run_config["configurable"]["thread_id"]
    initial_state: dict = {"user_input": input_data.user_input, "thread_id": thread_id}
    if input_data.user_id:
        initial_state["user_id"] = input_data.user_id
    if input_data.page_context is not None:
        initial_state["page_context"] = input_data.page_context
        if input_data.page_context.site_id is not None:
            initial_state["site_id"] = input_data.page_context.site_id

    # 状态追踪
    rag_sent = False       # RAG 来源是否已发送
    tools_called = False   # 是否已发送过 tool_call（区分 thinking vs text）
    tool_call_map = {}     # tool_call_id → tool_name 映射
    text_emitted = False   # 是否已发送过 text 事件
    text_sanitizer = _StreamingTextSanitizer()  # 流式文本清理器（逐 chunk 实时输出 + 尾部缓冲防跨 chunk 漏网）
    thinking_buffer = ""   # 缓存 thinking 内容（用于无工具调用时转为 text）
    is_memory_write = is_explicit_memory_write_request(input_data.user_input)
    memory_feedback_sent = False
    deferred_memory_text = ""
    final_report_sent = False
    intent_plan_sent = False
    action_keys_sent: set[str] = set()

    yield "event: thinking\ndata: {\"text\": \"已接收请求，正在分析...\"}\n\n"

    stream_slot_acquired = await _acquire_stream_slot()
    if not stream_slot_acquired:
        yield (
            "event: error\n"
            "data: {\"error\": \"当前请求较多，请稍后重试\"}\n\n"
        )
        yield "event: done\ndata: {}\n\n"
        return

    try:
        async_graph = await _get_stream_graph()
        graph_events = async_graph.astream_events(
            initial_state,
            config=run_config,
            version="v2",
        )
        started_at = time.monotonic()
        while True:
            wait_timeout = settings.api.stream_event_timeout_seconds or None
            if settings.api.stream_execution_timeout_seconds > 0:
                remaining = settings.api.stream_execution_timeout_seconds - (
                    time.monotonic() - started_at
                )
                if remaining <= 0:
                    raise asyncio.TimeoutError("Agent 执行超过时间预算")
                wait_timeout = min(wait_timeout, remaining) if wait_timeout else remaining
            try:
                event = await asyncio.wait_for(graph_events.__anext__(), timeout=wait_timeout)
            except StopAsyncIteration:
                break
            except asyncio.TimeoutError as exc:
                if settings.api.stream_execution_timeout_seconds > 0 and (
                    time.monotonic() - started_at
                ) >= settings.api.stream_execution_timeout_seconds:
                    raise asyncio.TimeoutError("Agent 执行超过时间预算") from exc
                raise asyncio.TimeoutError("等待 Agent 流式事件超时") from exc
            kind = event["event"]
            metadata = event.get("metadata", {})
            node = metadata.get("langgraph_node", "")

            # ── 流式文本：根据工具是否已调用来区分 thinking vs text ──
            if kind == "on_chat_model_stream":
                chunk = event["data"]["chunk"]
                if isinstance(chunk, AIMessageChunk) and chunk.content:
                    if node == "cognitive_parser":
                        if tools_called:
                            # 工具调用后的 cognitive_parser 是唯一的正文 token 流。
                            # 最终 final_report 仅在无 token 场景用作 SSE 兜底。
                            safe = text_sanitizer.feed(chunk.content)
                            if safe:
                                text_emitted = True
                                yield f"event: text\ndata: {json.dumps({'text': safe}, ensure_ascii=False)}\n\n"
                        else:
                            # 工具调用前的 cognitive_parser 输出 = 思考过程（保持实时流式）
                            thinking_buffer += chunk.content
                            yield f"event: thinking\ndata: {json.dumps({'text': chunk.content}, ensure_ascii=False)}\n\n"
                    elif node == "interpreter_generator":
                        if is_memory_write:
                            deferred_memory_text += chunk.content
                        else:
                            safe = text_sanitizer.feed(chunk.content)
                            if safe:
                                text_emitted = True
                                yield f"event: text\ndata: {json.dumps({'text': safe}, ensure_ascii=False)}\n\n"

            # ── 工具调用：从 cognitive_parser 的 tool_calls ──
            elif kind == "on_chat_model_end" and node == "cognitive_parser":
                output = event.get("data", {}).get("output", {})
                if hasattr(output, "tool_calls") and output.tool_calls:
                    tools_called = True
                    for tc in output.tool_calls:
                        # 记录 tool_call_id → name 映射
                        tc_id = tc.get("id", "")
                        if tc_id:
                            tool_call_map[tc_id] = tc["name"]
                        yield f"event: tool_call\ndata: {json.dumps({'name': tc['name'], 'args': tc.get('args', {})}, ensure_ascii=False)}\n\n"

            # ── 工具结果 + RAG 来源：从 v3_engine_router 的 chain_stream ──
            elif kind == "on_chain_stream" and node == "v3_engine_router":
                chunk = event.get("data", {}).get("chunk", {})
                if isinstance(chunk, dict):
                    messages = chunk.get("messages", [])
                    for msg in messages:
                        if isinstance(msg, ToolMessage) and msg.content:
                            # 通过 tool_call_id 查找工具名
                            tc_id = getattr(msg, "tool_call_id", "")
                            tool_name = tool_call_map.get(tc_id, getattr(msg, "name", "") or "unknown")
                            # 尝试解析 JSON 内容
                            try:
                                result = json.loads(msg.content)
                            except (json.JSONDecodeError, TypeError):
                                result = msg.content
                            yield f"event: tool_result\ndata: {json.dumps({'name': tool_name, 'result': result}, ensure_ascii=False, default=str)}\n\n"

                    # RAG 来源
                    if not rag_sent and chunk.get("hvac_knowledge"):
                        rag_sent = True
                        yield f"event: rag_sources\ndata: {json.dumps(chunk['hvac_knowledge'], ensure_ascii=False, default=str)}\n\n"

            # ── chain_end：intent_plan + action + rag_sources ──
            elif kind == "on_chain_end":
                output = event.get("data", {}).get("output", {})
                if isinstance(output, dict):
                    memory_feedback = output.get("memory_feedback")
                    if memory_feedback and not memory_feedback_sent:
                        memory_feedback_sent = True
                        text_emitted = True
                        thinking_buffer = ""
                        yield f"event: text\ndata: {json.dumps({'text': memory_feedback}, ensure_ascii=False)}\n\n"

                    # 统一以 State 中已经过节点后处理的 final_report 作为最终回答。
                    # 这覆盖“直接命中记忆查询”等没有 on_chat_model_stream 的路径，
                    # 并避免把 cognitive_parser 与 interpreter 的文本重复推给前端。
                    final_report = output.get("final_report")
                    if (
                        final_report
                        and not final_report_sent
                        and not memory_feedback_sent
                        and not text_emitted
                    ):
                        final_report_sent = True
                        text_emitted = True
                        thinking_buffer = ""
                        # 丢弃尚未达到实时输出阈值的 token 尾部，避免随后 flush
                        # 再次发出与 final_report 相同的短回答。
                        text_sanitizer.flush()
                        safe_report = _StreamingTextSanitizer._clean(str(final_report)).strip()
                        if safe_report:
                            yield f"event: text\ndata: {json.dumps({'text': safe_report}, ensure_ascii=False)}\n\n"

                    # intent_plan
                    intent_plan = output.get("intent_plan")
                    if intent_plan and not intent_plan_sent:
                        intent_plan_sent = True
                        intents_payload = [
                            i.model_dump() if isinstance(i, IntentItem)
                            else (i if isinstance(i, dict) else {"id": 0, "description": str(i)})
                            for i in intent_plan
                        ]
                        yield f"event: intent_plan\ndata: {json.dumps({'intents': intents_payload}, ensure_ascii=False)}\n\n"

                    # action
                    actions = output.get("pending_actions", [])
                    for action in actions:
                        payload = action.model_dump() if isinstance(action, UIAction) else action
                        action_key = json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True)
                        if action_key in action_keys_sent:
                            continue
                        action_keys_sent.add(action_key)
                        yield f"event: action\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"

                    # data_card（Phase 6 导出：表格 + 下载按钮）
                    data_cards = output.get("pending_data_cards", [])
                    for card in data_cards:
                        payload = card.model_dump() if hasattr(card, "model_dump") else card
                        yield f"event: data_card\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"

                    # RAG sources (fallback if not caught in chain_stream)
                    if not rag_sent and output.get("hvac_knowledge"):
                        rag_sent = True
                        yield f"event: rag_sources\ndata: {json.dumps(output['hvac_knowledge'], ensure_ascii=False, default=str)}\n\n"

    except asyncio.TimeoutError as e:
        logger.error(f"SSE 流式推送超时: {e}")
        yield f"event: error\ndata: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
    except Exception as e:
        logger.error(f"SSE 流式推送失败: {e}")
        yield f"event: error\ndata: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
    finally:
        _release_stream_slot(stream_slot_acquired)

    # 冲洗流式清理器尾部缓冲（兼容未来重新启用 token 级 final text）。
    tail = text_sanitizer.flush()
    if tail:
        text_emitted = True
        yield f"event: text\ndata: {json.dumps({'text': tail}, ensure_ascii=False)}\n\n"

    # 无工具调用时，cognitive_parser 的输出即为最终回答，补发为 text 事件
    # 场景：用户问通用问题，LLM 直接回答不调用工具
    if not text_emitted and deferred_memory_text:
        yield f"event: text\ndata: {json.dumps({'text': _StreamingTextSanitizer._clean(deferred_memory_text).strip()}, ensure_ascii=False)}\n\n"
    elif not text_emitted and thinking_buffer:
        yield f"event: text\ndata: {json.dumps({'text': _StreamingTextSanitizer._clean(thinking_buffer).strip()}, ensure_ascii=False)}\n\n"

    yield "event: done\ndata: {}\n\n"


@app.post("/stream")
async def stream(
    input_data: ActionAgentInput,
    _: None = Depends(_verify_api_key),
) -> StreamingResponse:
    """流式运行 Agent，以 SSE 格式推送细粒度事件。

    SSE 事件类型:
    - thinking: 思考过程文本（来自 cognitive_parser，可折叠/丢弃）
    - tool_call: 工具调用（name + args，可折叠/丢弃）
    - tool_result: 工具返回结果（name + result，可折叠/丢弃）
    - rag_sources: RAG 知识库检索结果（可折叠/丢弃）
    - text: 最终回答文本（来自 interpreter_generator，主体内容）
    - intent_plan: 多意图识别计划
    - action: 页面跳转动作
    - error: 错误信息
    - done: 流结束标志

    Args:
        input_data: 包含 user_input 和可选 page_context 的请求体

    Returns:
        StreamingResponse（media_type=text/event-stream）
    """
    return StreamingResponse(_sse_generator(input_data), media_type="text/event-stream")
