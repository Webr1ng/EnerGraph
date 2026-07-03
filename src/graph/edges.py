"""edges — 决策层 Agent 条件路由

所属层：graph
依赖：langchain_core, src.config.settings
对接算法层：N/A
"""
from langchain_core.messages import AIMessage, HumanMessage

from src.config.settings import settings
from src.graph.state import AgentState


def should_continue(state: AgentState) -> str:
    """判断下一步：调用工具 → 继续，否则 → 生成报告。

    Args:
        state: 当前 AgentState。

    Returns:
        tools 或 report。迭代上限仅统计最新用户消息后的当前轮 AI 消息。
    """
    messages = state.get("messages", [])
    if not messages or state.get("error"):
        return "report"

    last = messages[-1]
    if state.get("messages") and isinstance(last, AIMessage):
        latest_user_index = max(
            (index for index, message in enumerate(messages) if isinstance(message, HumanMessage)),
            default=-1,
        )
        iteration = sum(
            1
            for message in messages[latest_user_index + 1:]
            if isinstance(message, AIMessage)
        )
        if iteration >= settings.agent.max_iterations:
            return "report"
        if getattr(last, "tool_calls", None):
            return "tools"

    return "report"
