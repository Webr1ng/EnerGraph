"""FastAPI 服务层 — Action Agent HTTP API

所属层：services
依赖：fastapi, uvicorn, src.graph.builder, src.schemas, src.config.settings
对接算法层：N/A（通过 Graph 间接调用 Tools）
"""
import json
import logging
import secrets
from typing import AsyncIterator, List

from fastapi import Depends, FastAPI, HTTPException, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from langchain_core.messages import AIMessageChunk, ToolMessage

from src.config.settings import settings
from src.graph.builder import build_graph_config, graph
from src.schemas.action_agent import ActionAgentInput, UIAction
from src.schemas.v3_engine import IntentItem

logger = logging.getLogger(__name__)

app = FastAPI(
    title="EnerGraph Action Agent",
    description="青山 V3 多模态调度 Agent HTTP API",
    version="0.3.0",
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

    return JSONResponse(content={
        "report": report,
        "actions": actions_dicts,
        "thread_id": thread_id,
    })


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
    if input_data.page_context is not None:
        initial_state["page_context"] = input_data.page_context
        if input_data.page_context.site_id is not None:
            initial_state["site_id"] = input_data.page_context.site_id

    # 状态追踪
    rag_sent = False       # RAG 来源是否已发送
    tools_called = False   # 是否已发送过 tool_call（区分 thinking vs text）
    tool_call_map = {}     # tool_call_id → tool_name 映射
    text_emitted = False   # 是否已发送过 text 事件
    thinking_buffer = ""   # 缓存 thinking 内容（用于无工具调用时转为 text）

    try:
        async for event in graph.astream_events(
            initial_state,
            config=run_config,
            version="v2",
        ):
            kind = event["event"]
            metadata = event.get("metadata", {})
            node = metadata.get("langgraph_node", "")

            # ── 流式文本：根据工具是否已调用来区分 thinking vs text ──
            if kind == "on_chat_model_stream":
                chunk = event["data"]["chunk"]
                if isinstance(chunk, AIMessageChunk) and chunk.content:
                    if node == "cognitive_parser":
                        if tools_called:
                            # 工具已调用后的 cognitive_parser 输出 = 最终回答
                            text_emitted = True
                            yield f"event: text\ndata: {json.dumps({'text': chunk.content}, ensure_ascii=False)}\n\n"
                        else:
                            # 工具调用前的 cognitive_parser 输出 = 思考过程
                            thinking_buffer += chunk.content
                            yield f"event: thinking\ndata: {json.dumps({'text': chunk.content}, ensure_ascii=False)}\n\n"
                    elif node == "interpreter_generator":
                        # interpreter_generator 的输出也是最终回答
                        text_emitted = True
                        yield f"event: text\ndata: {json.dumps({'text': chunk.content}, ensure_ascii=False)}\n\n"

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
                    # intent_plan
                    intent_plan = output.get("intent_plan")
                    if intent_plan:
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
                        yield f"event: action\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"

                    # RAG sources (fallback if not caught in chain_stream)
                    if not rag_sent and output.get("hvac_knowledge"):
                        rag_sent = True
                        yield f"event: rag_sources\ndata: {json.dumps(output['hvac_knowledge'], ensure_ascii=False, default=str)}\n\n"

    except Exception as e:
        logger.error(f"SSE 流式推送失败: {e}")
        yield f"event: error\ndata: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"

    # 无工具调用时，cognitive_parser 的输出即为最终回答，补发为 text 事件
    # 场景：用户问通用问题，LLM 直接回答不调用工具
    if not text_emitted and thinking_buffer:
        yield f"event: text\ndata: {json.dumps({'text': thinking_buffer}, ensure_ascii=False)}\n\n"

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
