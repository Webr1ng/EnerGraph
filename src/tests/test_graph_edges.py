"""test_graph_edges — 多轮会话条件路由回归测试

所属层：tests
依赖：pytest, langchain_core, src.graph.edges
对接算法层：N/A
"""
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from src.graph import edges


def test_iteration_limit_ignores_previous_conversation_turns(monkeypatch) -> None:
    """历史 AI 消息达到上限时，当前新轮次仍应执行工具。"""
    monkeypatch.setattr(edges.settings.agent, "max_iterations", 2)
    state = {
        "messages": [
            SystemMessage(content="system"),
            HumanMessage(content="第一轮"),
            AIMessage(content="第一轮回答"),
            HumanMessage(content="第二轮"),
            AIMessage(content="第二轮回答"),
            HumanMessage(content="请导出本月报警明细"),
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "fetch_alarm_history", "args": {"site_id": "SH-01"}, "id": "tc-alarm"},
                ],
            ),
        ]
    }

    assert edges.should_continue(state) == "tools"


def test_iteration_limit_still_applies_within_current_turn(monkeypatch) -> None:
    """当前轮次自身达到上限后仍应停止 Tool 回环。"""
    monkeypatch.setattr(edges.settings.agent, "max_iterations", 2)
    state = {
        "messages": [
            SystemMessage(content="system"),
            HumanMessage(content="查询报警"),
            AIMessage(
                content="",
                tool_calls=[{"name": "fetch_alarm_history", "args": {}, "id": "tc-1"}],
            ),
            ToolMessage(content="{}", tool_call_id="tc-1"),
            AIMessage(
                content="",
                tool_calls=[{"name": "export_data_table", "args": {}, "id": "tc-2"}],
            ),
        ]
    }

    assert edges.should_continue(state) == "report"
