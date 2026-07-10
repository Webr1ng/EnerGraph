"""test_action_agent — /stream 端点集成测试

所属层：tests
依赖：fastapi, httpx, pytest, unittest.mock
对接算法层：N/A（Mock graph.astream_events）
"""
import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.config.settings import settings
from src.services.api import app
from src.schemas.action_agent import UIAction

TEST_ROUTE = "/integrated-monitor/conditioning-terminal"


def _make_action_event():
    action = UIAction(route=TEST_ROUTE, params={"site_id": "SH-01"})
    return action


async def _mock_astream_events(initial_state, config=None, version="v2"):
    """模拟 graph.astream_events，依次产出 thinking、tool_call、tool_result、text、action、done 事件。"""
    from langchain_core.messages import AIMessageChunk, ToolMessage

    # thinking 事件（cognitive_parser 工具调用前的思考）
    yield {
        "event": "on_chat_model_stream",
        "metadata": {"langgraph_node": "cognitive_parser"},
        "data": {"chunk": AIMessageChunk(content="让我查询一下")},
    }
    # tool_call 事件（cognitive_parser 决定调用工具）
    from unittest.mock import MagicMock
    mock_output = MagicMock()
    mock_output.tool_calls = [{"name": "fetch_cop_data", "args": {"site_id": "SH-01"}, "id": "call_01"}]
    yield {
        "event": "on_chat_model_end",
        "metadata": {"langgraph_node": "cognitive_parser"},
        "data": {"output": mock_output},
    }
    # tool_result 事件（v3_engine_router 返回工具结果）
    tool_msg = ToolMessage(content='{"cumulative_cop": 4.2}', tool_call_id="call_01")
    yield {
        "event": "on_chain_stream",
        "metadata": {"langgraph_node": "v3_engine_router"},
        "data": {"chunk": {"messages": [tool_msg]}},
    }
    # text 事件（cognitive_parser 工具调用后的最终回答）
    yield {
        "event": "on_chat_model_stream",
        "metadata": {"langgraph_node": "cognitive_parser"},
        "data": {"chunk": AIMessageChunk(content="冷水机房当前 COP 为 4.2")},
    }
    # action 事件（通过 on_chain_end 携带 pending_actions）
    yield {
        "event": "on_chain_end",
        "data": {"output": {
            "pending_actions": [_make_action_event()],
            "final_report": "冷水机房当前 COP 为 4.2",
        }},
    }


@pytest.mark.asyncio
async def test_stream_contains_action_event():
    with patch("src.services.api.graph") as mock_graph:
        mock_graph.astream_events = _mock_astream_events

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/stream",
                json={
                    "user_input": "冷水机房的 COP 是多少？",
                    "page_context": {"current_route": TEST_ROUTE, "site_id": "SH-01"},
                },
            )

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]

    body = response.text
    event_types = [
        line.removeprefix("event: ").strip()
        for line in body.splitlines()
        if line.startswith("event:")
    ]

    assert "thinking" in event_types, f"缺少 thinking 事件，实际事件：{event_types}"
    assert "tool_call" in event_types, f"缺少 tool_call 事件，实际事件：{event_types}"
    assert "tool_result" in event_types, f"缺少 tool_result 事件，实际事件：{event_types}"
    assert "text" in event_types, f"缺少 text 事件，实际事件：{event_types}"
    assert "action" in event_types, f"缺少 action 事件，实际事件：{event_types}"
    assert "done" in event_types, f"缺少 done 事件，实际事件：{event_types}"
    assert event_types[0] == "thinking"
    assert "已接收请求" in body

    # 验证 tool_call payload
    tool_call_lines = [
        line.removeprefix("data: ").strip()
        for i, line in enumerate(body.splitlines())
        if i > 0 and body.splitlines()[i - 1].strip() == "event: tool_call"
    ]
    assert tool_call_lines, "tool_call 事件缺少 data 行"
    tc_payload = json.loads(tool_call_lines[0])
    assert tc_payload.get("name") == "fetch_cop_data"

    # 验证 action payload 包含正确路由
    action_lines = [
        line.removeprefix("data: ").strip()
        for i, line in enumerate(body.splitlines())
        if i > 0 and body.splitlines()[i - 1].strip() == "event: action"
    ]
    assert action_lines, "action 事件缺少 data 行"
    payload = json.loads(action_lines[0])
    assert payload.get("route") == TEST_ROUTE


@pytest.mark.asyncio
async def test_stream_returns_error_when_concurrency_slot_unavailable(monkeypatch):
    """并发槽耗尽时 /stream 应快速返回 error+done，避免请求无限排队。"""
    import src.services.api as api_module

    class _ShouldNotRunGraph:
        async def astream_events(self, *_args, **_kwargs):
            raise AssertionError("graph should not run when stream slot is unavailable")

    monkeypatch.setattr(api_module, "graph", _ShouldNotRunGraph())
    monkeypatch.setattr(api_module, "_STREAM_SEMAPHORE", asyncio.Semaphore(0))
    monkeypatch.setattr(settings.api, "stream_queue_timeout_seconds", 0.001)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/stream",
            json={"user_input": "查一下 COP", "thread_id": "busy-stream"},
        )

    assert response.status_code == 200
    assert "event: thinking" in response.text
    assert "event: error" in response.text
    assert "当前请求较多" in response.text
    assert response.text.rstrip().endswith("event: done\ndata: {}")


@pytest.mark.asyncio
async def test_stream_returns_error_when_graph_event_timeout(monkeypatch):
    """Graph 长时间不产出事件时 /stream 应返回超时错误并释放并发槽。"""
    import src.services.api as api_module
    from langchain_core.messages import AIMessageChunk

    class _StalledGraph:
        async def astream_events(self, *_args, **_kwargs):
            await asyncio.sleep(0.05)
            yield {
                "event": "on_chat_model_stream",
                "metadata": {"langgraph_node": "cognitive_parser"},
                "data": {"chunk": AIMessageChunk(content="too late")},
            }

    semaphore = asyncio.Semaphore(1)
    monkeypatch.setattr(api_module, "graph", _StalledGraph())
    monkeypatch.setattr(api_module, "_STREAM_SEMAPHORE", semaphore)
    monkeypatch.setattr(settings.api, "stream_queue_timeout_seconds", 0.001)
    monkeypatch.setattr(settings.api, "stream_event_timeout_seconds", 0.001)
    monkeypatch.setattr(settings.api, "stream_execution_timeout_seconds", 1.0)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/stream",
            json={"user_input": "查一下 COP", "thread_id": "timeout-stream"},
        )

    assert response.status_code == 200
    assert "event: error" in response.text
    assert "等待 Agent 流式事件超时" in response.text
    assert "event: done" in response.text
    assert semaphore._value == 1


@pytest.mark.asyncio
async def test_memory_write_stream_emits_only_post_persist_feedback():
    """显式记忆写入 SSE 不发送写库前旧回答，只发送 memory_feedback。"""
    from langchain_core.messages import AIMessageChunk

    async def _memory_events(initial_state, config=None, version="v2"):
        yield {
            "event": "on_chat_model_stream",
            "metadata": {"langgraph_node": "interpreter_generator"},
            "data": {"chunk": AIMessageChunk(content="旧记忆仍是先给结论")},
        }
        yield {
            "event": "on_chain_end",
            "metadata": {"langgraph_node": "memory_manager"},
            "data": {
                "output": {
                    "memory_feedback": "已更新长期偏好：先给数据，最后给结论"
                }
            },
        }

    with patch("src.services.api.graph") as mock_graph:
        mock_graph.astream_events = _memory_events
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/stream",
                json={"user_input": "请更新我的偏好：先给数据，最后给结论"},
            )

    assert "已更新长期偏好" in response.text
    assert "旧记忆仍是先给结论" not in response.text


@pytest.mark.asyncio
async def test_memory_write_stream_falls_back_when_feedback_missing():
    """记忆后台异常未返回 feedback 时，SSE 不吞掉 interpreter 原回答。"""
    from langchain_core.messages import AIMessageChunk

    async def _memory_events(initial_state, config=None, version="v2"):
        yield {
            "event": "on_chat_model_stream",
            "metadata": {"langgraph_node": "interpreter_generator"},
            "data": {"chunk": AIMessageChunk(content="记忆写入暂时失败，请稍后重试。")},
        }

    with patch("src.services.api.graph") as mock_graph:
        mock_graph.astream_events = _memory_events
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/stream",
                json={"user_input": "请记住以后回答简洁"},
            )

    assert "记忆写入暂时失败" in response.text


@pytest.mark.asyncio
async def test_stream_page_context_injected_into_system_prompt():
    """验证 page_context 被注入到 cognitive_parser 的 system prompt 中。"""
    captured_messages = []

    async def _capture_astream_events(initial_state, config=None, version="v2"):
        # 触发 cognitive_parser_node 以捕获注入后的 messages
        from src.graph.nodes import cognitive_parser_node
        from src.schemas.action_agent import PageContext

        state = {
            "user_input": "查询 COP",
            "page_context": PageContext(current_route=TEST_ROUTE, site_id="SH-01"),
        }
        # 直接调用节点（不走 LLM），只验证 messages 构造
        # mock LLM invoke
        from unittest.mock import MagicMock
        from langchain_core.messages import AIMessage

        with patch("src.graph.nodes._get_llm") as mock_llm_factory:
            mock_llm = MagicMock()
            mock_llm.invoke.return_value = AIMessage(content="ok", tool_calls=[])
            mock_llm_factory.return_value = mock_llm
            result = cognitive_parser_node(state)
            captured_messages.extend(result.get("messages", []))

        yield {"event": "on_chain_end", "data": {"output": {}}}

    with patch("src.services.api.graph") as mock_graph:
        mock_graph.astream_events = _capture_astream_events

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.post(
                "/stream",
                json={
                    "user_input": "查询 COP",
                    "page_context": {"current_route": TEST_ROUTE, "site_id": "SH-01"},
                },
            )

    system_msg = next((m for m in captured_messages if hasattr(m, "type") and m.type == "system"), None)
    assert system_msg is not None, "未找到 SystemMessage"
    assert TEST_ROUTE in system_msg.content, "current_route 未注入 system prompt"
    assert "SH-01" in system_msg.content, "site_id 未注入 system prompt"


@pytest.mark.asyncio
async def test_page_context_fallback_none_site_id():
    """验证 PageContext 为 Pydantic 对象且 site_id 为 None 时不崩溃。"""
    from unittest.mock import MagicMock, patch
    from langchain_core.messages import AIMessage
    from src.graph.nodes import cognitive_parser_node
    from src.schemas.action_agent import PageContext

    state = {
        "user_input": "查询 COP",
        "page_context": PageContext(current_route="/", site_id=None),
    }

    with patch("src.graph.nodes._get_llm") as mock_llm_factory:
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = AIMessage(content="ok", tool_calls=[])
        mock_llm_factory.return_value = mock_llm
        result = cognitive_parser_node(state)

    messages = result.get("messages", [])
    system_msg = next((m for m in messages if hasattr(m, "type") and m.type == "system"), None)
    assert system_msg is not None
    assert "未指定" in system_msg.content, "site_id=None 时应显示'未指定'"


# ── UIAction 路由标准化和名称填充测试 ─────────────────────────────────


def test_ui_action_has_name_field():
    """验证 UIAction 模型包含 name 字段。"""
    from src.schemas.action_agent import UIAction

    action = UIAction(route="/analysis/consumption-panel", name="能耗分析")
    assert action.name == "能耗分析"
    assert action.route == "/analysis/consumption-panel"


@pytest.mark.asyncio
async def test_stream_passes_thread_id_to_langgraph_config():
    """验证 /stream 会把 thread_id 传入 LangGraph checkpointer config。"""
    captured = {}

    async def _capture_config(initial_state, config=None, version="v2"):
        captured["initial_state"] = initial_state
        captured["config"] = config
        yield {"event": "on_chain_end", "data": {"output": {}}}

    with patch("src.services.api.graph") as mock_graph:
        mock_graph.astream_events = _capture_config

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/stream",
                json={
                    "user_input": "查询 COP",
                    "thread_id": "thread-test-01",
                    "user_id": "user-test-01",
                    "page_context": {"current_route": TEST_ROUTE, "site_id": "SH-01"},
                },
            )

    assert response.status_code == 200
    assert captured["initial_state"]["thread_id"] == "thread-test-01"
    assert captured["initial_state"]["user_id"] == "user-test-01"
    assert captured["initial_state"]["site_id"] == "SH-01"
    assert captured["config"]["configurable"]["thread_id"] == "thread-test-01"


def test_ui_action_name_defaults_to_empty():
    """验证 UIAction name 字段默认为空字符串（向后兼容）。"""
    from src.schemas.action_agent import UIAction

    action = UIAction(route="/analysis/consumption-panel")
    assert action.name == ""


@pytest.mark.asyncio
async def test_worker_startup_prewarm_can_be_disabled(monkeypatch):
    """测试/特殊部署可关闭 Worker RAG 预热。"""
    from src.services.api import _prewarm_worker_dependencies

    monkeypatch.setattr(settings.rag, "prewarm_on_startup", False)
    await _prewarm_worker_dependencies()


def test_infer_navigation_normalizes_routes():
    """验证路由标准化：无 / 前缀的路由会被补全。"""
    from src.skills.ui_router_skill import UIRouterSkill

    # 模拟 LLM 返回无 / 前缀的路由
    tool_results = [
        ("navigate_to_page", {"route": "smart-maintenance/equipment-operation"}, {}),
    ]

    actions = UIRouterSkill._infer_navigation(tool_results)
    assert len(actions) == 1
    assert actions[0].route == "/smart-maintenance/equipment-operation"


def test_infer_navigation_deduplicates_normalized_routes():
    """验证路由去重：标准化后相同的路由只保留一个。"""
    from src.skills.ui_router_skill import UIRouterSkill

    # 模拟 LLM 同时调用 navigate_to_page（无 /）和工具自动推断（有 /）
    tool_results = [
        ("navigate_to_page", {"route": "analysis/consumption-panel"}, {}),
        ("fetch_energy_summary", {"total_consumption_kwh": 4083.5}, {"site_id": "FJJB000001"}),
    ]

    actions = UIRouterSkill._infer_navigation(tool_results)

    # 检查 /analysis/consumption-panel 只出现一次
    consumption_panel_count = sum(
        1 for a in actions if a.route == "/analysis/consumption-panel"
    )
    assert consumption_panel_count == 1, f"路由 /analysis/consumption-panel 出现 {consumption_panel_count} 次，应为 1 次"


def test_infer_navigation_fills_name_from_routes():
    """验证路由名称自动填充。"""
    from src.skills.ui_router_skill import UIRouterSkill

    tool_results = [
        ("fetch_energy_summary", {"total_consumption_kwh": 4083.5}, {"site_id": "FJJB000001"}),
    ]

    actions = UIRouterSkill._infer_navigation(tool_results)

    # fetch_energy_summary 映射到两个页面：能耗分析 + 光储实时能量
    assert len(actions) == 2
    routes = {a.route: a.name for a in actions}
    assert routes.get("/analysis/consumption-panel") == "能耗分析"
    assert routes.get("/coordination/energy") == "光储实时能量"


def test_infer_navigation_no_duplicate_same_route():
    """验证完全相同的路由不会重复出现。"""
    from src.skills.ui_router_skill import UIRouterSkill

    # 模拟多次工具调用可能产生相同路由
    tool_results = [
        ("navigate_to_page", {"route": "/analysis/consumption-panel"}, {}),
        ("navigate_to_page", {"route": "/analysis/consumption-panel"}, {}),  # 重复
    ]

    actions = UIRouterSkill._infer_navigation(tool_results)

    # 应该只有一个 /analysis/consumption-panel
    assert len(actions) == 1
    assert actions[0].route == "/analysis/consumption-panel"
