"""test_multi_intent — Phase 7 多意图识别与拆分执行测试

所属层：tests
依赖：pytest, unittest.mock
对接算法层：N/A（Mock LLM / Graph）

测试范围：
  - T1: IntentItem 模型序列化 + AgentState intent_plan 字段
  - T2: cognitive_parser Prompt 包含多意图指令 + 多 tool_calls 构建 intent_plan
  - T3: interpreter_generator 输出分段报告（## 1. / ## 2.）
  - T4: SSE intent_plan 事件推送
"""
import json
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from src.schemas.v3_engine import IntentItem


# ---------------------------------------------------------------------------
# T1: IntentItem 模型
# ---------------------------------------------------------------------------


class TestIntentItem:
    """IntentItem Pydantic 模型测试"""

    def test_basic_creation(self):
        """基本创建：id + description"""
        item = IntentItem(id=1, description="COP 查询")
        assert item.id == 1
        assert item.description == "COP 查询"
        assert item.category == "general"
        assert item.depends_on == []
        assert item.status == "pending"

    def test_with_category_and_dependencies(self):
        """带类别和依赖关系的创建"""
        item = IntentItem(
            id=2, description="排产建议", category="energy",
            depends_on=[1], status="pending",
        )
        assert item.category == "energy"
        assert item.depends_on == [1]

    def test_serialization(self):
        """序列化 / 反序列化"""
        item = IntentItem(id=1, description="COP 查询", category="monitor")
        data = item.model_dump()
        assert data["id"] == 1
        assert data["category"] == "monitor"

        restored = IntentItem(**data)
        assert restored == item

    def test_status_transitions(self):
        """状态字段可更新"""
        item = IntentItem(id=1, description="test")
        assert item.status == "pending"
        item.status = "running"
        assert item.status == "running"
        item.status = "done"
        assert item.status == "done"

    def test_json_serializable(self):
        """可 JSON 序列化（用于 SSE 推送）"""
        items = [
            IntentItem(id=1, description="COP 查询", category="monitor"),
            IntentItem(id=2, description="能耗导出", category="export"),
        ]
        payload = json.dumps([i.model_dump() for i in items], ensure_ascii=False)
        parsed = json.loads(payload)
        assert len(parsed) == 2
        assert parsed[0]["id"] == 1
        assert parsed[1]["category"] == "export"


# ---------------------------------------------------------------------------
# T1: AgentState intent_plan 字段
# ---------------------------------------------------------------------------


class TestAgentStateIntentPlan:
    """AgentState intent_plan 字段测试"""

    def test_state_accepts_intent_plan(self):
        """AgentState 可存储 intent_plan"""
        from src.graph.state import AgentState

        plan = [
            IntentItem(id=1, description="COP 查询"),
            IntentItem(id=2, description="报警查询"),
        ]
        state: AgentState = {
            "user_input": "查 COP 和报警",
            "intent_plan": plan,
        }
        assert len(state["intent_plan"]) == 2
        assert state["intent_plan"][0].description == "COP 查询"

    def test_state_intent_plan_optional(self):
        """intent_plan 为可选字段"""
        from src.graph.state import AgentState

        state: AgentState = {"user_input": "单一问题"}
        assert state.get("intent_plan") is None


# ---------------------------------------------------------------------------
# T2: cognitive_parser Prompt 多意图指令
# ---------------------------------------------------------------------------


class TestCognitiveParserMultiIntent:
    """cognitive_parser Prompt 和 intent_plan 构建测试"""

    def test_prompt_contains_multi_intent_instructions(self):
        """prompts/main_graph.yaml 中 cognitive_parser 应包含多意图识别指令"""
        from src.graph.nodes import _load_prompts

        prompts = _load_prompts()
        content = prompts["cognitive_parser"]["system"]
        assert "多意图识别" in content
        assert "多个独立请求" in content
        assert "数据依赖" in content

    def test_prompt_contains_parallel_example(self):
        """Prompt 应包含并行执行和多意图识别指令（新架构：Agent 路由）"""
        from src.graph.nodes import _load_prompts

        prompts = _load_prompts()
        content = prompts["cognitive_parser"]["system"]
        # 新架构：检查 Agent 路由指令而非具体工具示例
        assert "hvac_expert Agent" in content or "ui_router Agent" in content or "powerai Agent" in content
        assert "并行执行" in content or "多个工具并行" in content

    def test_multi_tool_calls_build_intent_plan(self):
        """LLM 返回多个 tool_calls 时，cognitive_parser_node 构建 intent_plan"""
        from src.graph.nodes import cognitive_parser_node

        state = {"user_input": "查 COP 和能耗"}

        # Mock LLM 返回 2 个 tool_calls
        mock_response = AIMessage(
            content="",
            tool_calls=[
                {"name": "fetch_cop_data", "args": {"site_id": "SH-01"}, "id": "tc1"},
                {"name": "fetch_energy_summary", "args": {"site_id": "SH-01", "date": "2026-06-04"}, "id": "tc2"},
            ],
        )

        with patch("src.graph.nodes._get_llm") as mock_factory:
            mock_llm = MagicMock()
            mock_llm.invoke.return_value = mock_response
            mock_factory.return_value = mock_llm
            result = cognitive_parser_node(state)

        assert "intent_plan" in result, "多 tool_calls 应生成 intent_plan"
        plan = result["intent_plan"]
        assert len(plan) == 2
        assert plan[0].category == "monitor"
        assert plan[1].category == "monitor"
        assert plan[0].id == 1
        assert plan[1].id == 2

    def test_single_tool_call_no_intent_plan(self):
        """LLM 返回单个 tool_call 时，不构建 intent_plan"""
        from src.graph.nodes import cognitive_parser_node

        state = {"user_input": "查 COP"}

        mock_response = AIMessage(
            content="",
            tool_calls=[
                {"name": "fetch_cop_data", "args": {"site_id": "SH-01"}, "id": "tc1"},
            ],
        )

        with patch("src.graph.nodes._get_llm") as mock_factory:
            mock_llm = MagicMock()
            mock_llm.invoke.return_value = mock_response
            mock_factory.return_value = mock_llm
            result = cognitive_parser_node(state)

        assert result.get("intent_plan") is None, "单 tool_call 不应保留旧 intent_plan"

    def test_no_tool_calls_no_intent_plan(self):
        """LLM 无 tool_calls 时，不构建 intent_plan"""
        from src.graph.nodes import cognitive_parser_node

        state = {"user_input": "你好"}

        mock_response = AIMessage(content="你好！我是福加能碳管理平台的 AI 助手。")

        with patch("src.graph.nodes._get_llm") as mock_factory:
            mock_llm = MagicMock()
            mock_llm.invoke.return_value = mock_response
            mock_factory.return_value = mock_llm
            result = cognitive_parser_node(state)

        assert result.get("intent_plan") is None

    def test_checkpoint_resume_appends_new_user_input(self):
        """checkpoint 恢复多轮会话时，应把本轮 user_input 追加给 LLM。"""
        from src.graph.nodes import cognitive_parser_node

        state = {
            "user_input": "我们冷水机房的能效（COP）怎么样？",
            "messages": [
                SystemMessage(content="system"),
                HumanMessage(content="请记住：我偏好默认看日维度和 COP"),
                AIMessage(content="已记住您的偏好"),
            ],
        }
        mock_response = AIMessage(content="正在查询 COP", tool_calls=[])

        with patch("src.graph.nodes._get_llm") as mock_factory:
            mock_llm = MagicMock()
            mock_llm.invoke.return_value = mock_response
            mock_factory.return_value = mock_llm
            result = cognitive_parser_node(state)

        invoked_messages = mock_llm.invoke.call_args[0][0]
        assert isinstance(invoked_messages[-1], HumanMessage)
        assert "冷水机房" in invoked_messages[-1].content
        returned_messages = result.get("messages", [])
        assert len(returned_messages) == 2
        assert isinstance(returned_messages[0], HumanMessage)
        assert returned_messages[1].content == "正在查询 COP"

    def test_new_turn_clears_stale_hvac_and_intent_state(self):
        """新轮次查询报警时不得继承上一轮 HVAC 与多意图状态。"""
        from src.graph.nodes import cognitive_parser_node

        state = {
            "user_input": "请导出本月报警明细，仅返回表格和 CSV，不生成图表。",
            "messages": [
                SystemMessage(content="system"),
                HumanMessage(content="查询 HVAC 知识"),
                AIMessage(content="上一轮 HVAC 回答"),
            ],
            "hvac_knowledge": {"answer": "旧 HVAC 数据"},
            "hvac_context_hint": {"system_suffix": "旧 HVAC 提示"},
            "intent_plan": [IntentItem(id=1, description="旧 HVAC 意图")],
            "final_report": "旧 HVAC 报告",
        }
        mock_response = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "fetch_alarm_history",
                    "args": {"site_id": "SH-01"},
                    "id": "tc-alarm",
                }
            ],
        )

        with patch("src.graph.nodes._get_llm") as mock_factory:
            mock_llm = MagicMock()
            mock_llm.invoke.return_value = mock_response
            mock_factory.return_value = mock_llm
            result = cognitive_parser_node(state)

        assert result["hvac_knowledge"] is None
        assert result["hvac_context_hint"] is None
        assert result["intent_plan"] is None
        assert result["final_report"] == ""

    def test_tool_loop_preserves_current_turn_hvac_state(self):
        """同一轮 Tool 回环不得清空刚获得的 HVAC 状态。"""
        from src.graph.nodes import cognitive_parser_node

        state = {
            "user_input": "查询 HVAC 知识",
            "messages": [
                SystemMessage(content="system"),
                HumanMessage(content="查询 HVAC 知识"),
                AIMessage(
                    content="",
                    tool_calls=[
                        {"name": "query_hvac_knowledge", "args": {"query": "COP"}, "id": "tc-hvac"},
                    ],
                ),
                ToolMessage(content='{"answer": "COP"}', tool_call_id="tc-hvac"),
            ],
            "hvac_knowledge": {"answer": "COP"},
        }
        mock_response = AIMessage(content="COP 回答")

        with patch("src.graph.nodes._get_llm") as mock_factory:
            mock_llm = MagicMock()
            mock_llm.invoke.return_value = mock_response
            mock_factory.return_value = mock_llm
            result = cognitive_parser_node(state)

        assert "hvac_knowledge" not in result

    def test_tool_loop_does_not_append_duplicate_user_input(self):
        """工具回环时最后一条是 ToolMessage，不应重复追加用户输入。"""
        from src.graph.nodes import cognitive_parser_node

        state = {
            "user_input": "查 COP",
            "messages": [
                SystemMessage(content="system"),
                HumanMessage(content="查 COP"),
                AIMessage(
                    content="",
                    tool_calls=[
                        {"name": "fetch_cop_data", "args": {"site_id": "SH-01"}, "id": "tc1"},
                    ],
                ),
                ToolMessage(content='{"cop": 4.2}', tool_call_id="tc1"),
            ],
        }
        mock_response = AIMessage(content="COP 为 4.2", tool_calls=[])

        with patch("src.graph.nodes._get_llm") as mock_factory:
            mock_llm = MagicMock()
            mock_llm.invoke.return_value = mock_response
            mock_factory.return_value = mock_llm
            result = cognitive_parser_node(state)

        invoked_messages = mock_llm.invoke.call_args[0][0]
        assert isinstance(invoked_messages[-1], ToolMessage)
        assert result.get("messages") == [mock_response]


# ---------------------------------------------------------------------------
# T3: interpreter_generator 分段报告
# ---------------------------------------------------------------------------


class TestInterpreterSegmentedReport:
    """interpreter_generator 分段报告测试"""

    def test_prompt_contains_segment_instructions(self):
        """prompts/main_graph.yaml 中 interpreter_generator 应包含分段报告指令"""
        from src.graph.nodes import _load_prompts

        prompts = _load_prompts()
        content = prompts["interpreter_generator"]["system"]
        assert "多意图分段报告" in content
        assert "## 1." in content
        assert "小结" in content

    def test_intent_plan_injected_into_system_prompt(self):
        """intent_plan 存在时，注入到 interpreter_generator 的 system prompt"""
        from src.graph.nodes import interpreter_generator_node

        plan = [
            IntentItem(id=1, description="COP 查询", status="done"),
            IntentItem(id=2, description="能耗查询", status="done"),
        ]

        # 构造一个 AIMessage（无 tool_calls）以触发直接返回路径
        state = {
            "user_input": "查 COP 和能耗",
            "messages": [
                SystemMessage(content="system"),
                HumanMessage(content="查 COP 和能耗"),
                AIMessage(content="", tool_calls=[
                    {"name": "fetch_cop_data", "args": {"site_id": "SH-01"}, "id": "tc1"},
                ]),
                ToolMessage(content="{}", tool_call_id="tc1"),
                AIMessage(content="", tool_calls=[
                    {"name": "fetch_energy_summary", "args": {"site_id": "SH-01", "date": "2026-06-04"}, "id": "tc2"},
                ]),
                ToolMessage(content="{}", tool_call_id="tc2"),
            ],
            "intent_plan": plan,
        }

        with patch("src.graph.nodes._get_llm") as mock_factory:
            mock_llm = MagicMock()
            mock_llm.invoke.return_value = AIMessage(content="## 1. COP\n...\n## 2. 能耗\n...")
            mock_factory.return_value = mock_llm

            result = interpreter_generator_node(state)

            # 验证 LLM 被调用时 system prompt 包含 intent_plan 信息
            call_args = mock_llm.invoke.call_args
            messages = call_args[0][0]
            system_msg = messages[0]
            assert "意图 1" in system_msg.content
            assert "COP 查询" in system_msg.content
            assert "意图 2" in system_msg.content
            assert "能耗查询" in system_msg.content

    def test_no_intent_plan_no_injection(self):
        """intent_plan 为空时，不注入额外内容"""
        from src.graph.nodes import interpreter_generator_node

        state = {
            "user_input": "查 COP",
            "messages": [
                SystemMessage(content="system"),
                HumanMessage(content="查 COP"),
                AIMessage(content="", tool_calls=[
                    {"name": "fetch_cop_data", "args": {"site_id": "SH-01"}, "id": "tc1"},
                ]),
                ToolMessage(content="{}", tool_call_id="tc1"),
            ],
            # 无 intent_plan
        }

        with patch("src.graph.nodes._get_llm") as mock_factory:
            mock_llm = MagicMock()
            mock_llm.invoke.return_value = AIMessage(content="COP 报告")
            mock_factory.return_value = mock_llm

            result = interpreter_generator_node(state)

            call_args = mock_llm.invoke.call_args
            messages = call_args[0][0]
            system_msg = messages[0]
            assert "本次处理的用户意图" not in system_msg.content


# ---------------------------------------------------------------------------
# T4: SSE intent_plan 事件
# ---------------------------------------------------------------------------


class TestSSEIntentPlanEvent:
    """SSE intent_plan 事件推送测试"""

    @pytest.mark.asyncio
    async def test_sse_emits_intent_plan_event(self):
        """多意图输入时，SSE 流应包含 event: intent_plan"""
        from httpx import ASGITransport, AsyncClient
        from src.services.api import app
        from src.schemas.action_agent import UIAction

        async def _mock_astream_events(initial_state, config=None, version="v2"):
            # 模拟 cognitive_parser 输出 intent_plan
            yield {
                "event": "on_chain_end",
                "data": {"output": {
                    "intent_plan": [
                        IntentItem(id=1, description="COP 查询", category="monitor"),
                        IntentItem(id=2, description="能耗查询", category="monitor"),
                    ],
                }},
            }
            # 模拟 text 输出
            yield {
                "event": "on_chat_model_stream",
                "data": {"chunk": type("Chunk", (), {"content": "报告内容"})()},
            }

        with patch("src.services.api.graph") as mock_graph:
            mock_graph.astream_events = _mock_astream_events

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post(
                    "/stream",
                    json={
                        "user_input": "查 COP 和能耗",
                        "page_context": {"current_route": "/", "site_id": "SH-01"},
                    },
                )

        assert response.status_code == 200
        body = response.text
        event_types = [
            line.removeprefix("event: ").strip()
            for line in body.splitlines()
            if line.startswith("event:")
        ]

        assert "intent_plan" in event_types, f"缺少 intent_plan 事件，实际：{event_types}"
        assert "done" in event_types

        # 验证 intent_plan payload
        intent_lines = [
            line.removeprefix("data: ").strip()
            for i, line in enumerate(body.splitlines())
            if i > 0 and body.splitlines()[i - 1].strip() == "event: intent_plan"
        ]
        assert intent_lines, "intent_plan 事件缺少 data 行"
        payload = json.loads(intent_lines[0])
        assert "intents" in payload
        assert len(payload["intents"]) == 2
        assert payload["intents"][0]["id"] == 1
