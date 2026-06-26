"""builder — 组装并编译决策层 LangGraph 状态图

所属层：graph
依赖：langgraph, src.graph.*
对接算法层：N/A
"""
import logging
import os
import uuid
from typing import Any, Optional

from langgraph.graph import END, StateGraph

from src.config.settings import settings
from src.graph.edges import should_continue
from src.graph.nodes import (
    cognitive_parser_node,
    interpreter_generator_node,
    memory_manager_node,
    v3_engine_router_node,
)
from src.graph.state import AgentState

logger = logging.getLogger(__name__)
_CHECKPOINT_CONN: Optional[Any] = None


def _build_checkpointer() -> Optional[Any]:
    """构建 LangGraph checkpointer。

    Returns:
        checkpointer 实例；依赖不可用时返回 None。
    """
    global _CHECKPOINT_CONN

    if settings.memory.strict_msgpack:
        os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")

    if settings.memory.enabled:
        try:
            import psycopg
            from psycopg.rows import dict_row
            from langgraph.checkpoint.postgres import PostgresSaver

            _CHECKPOINT_CONN = psycopg.connect(
                settings.memory.postgres_dsn,
                autocommit=True,
                row_factory=dict_row,
            )
            checkpointer = PostgresSaver(_CHECKPOINT_CONN)
            checkpointer.setup()
            logger.info("PostgresSaver checkpoint 已启用并完成 setup")
            return checkpointer
        except Exception as exc:
            logger.warning(f"PostgresSaver 启用失败，回退内存 checkpoint: {exc}")

    try:
        from langgraph.checkpoint.memory import MemorySaver

        return MemorySaver()
    except Exception as exc:
        logger.warning(f"MemorySaver 不可用，graph 将无 checkpoint: {exc}")
        return None


def build_graph():
    """构建并返回编译后的决策层调度 Agent 状态图。"""
    g = StateGraph(AgentState)

    g.add_node("cognitive_parser", cognitive_parser_node)
    g.add_node("v3_engine_router", v3_engine_router_node)
    g.add_node("interpreter_generator", interpreter_generator_node)
    g.add_node("memory_manager", memory_manager_node)

    g.set_entry_point("cognitive_parser")

    g.add_conditional_edges(
        "cognitive_parser",
        should_continue,
        {"tools": "v3_engine_router", "report": "interpreter_generator"},
    )
    g.add_edge("v3_engine_router", "cognitive_parser")
    g.add_edge("interpreter_generator", "memory_manager")
    g.add_edge("memory_manager", END)

    checkpointer = _build_checkpointer()
    if checkpointer is None:
        return g.compile()
    return g.compile(checkpointer=checkpointer)


def build_graph_config(thread_id: Optional[str] = None) -> dict:
    """构建 LangGraph checkpointer 运行配置。

    Args:
        thread_id: 会话线程 ID；为空时生成新的 UUID，避免不同请求共用 checkpoint。

    Returns:
        可传入 graph.invoke / graph.stream / graph.astream_events 的 config。
    """
    resolved_thread_id = thread_id or f"thread-{uuid.uuid4().hex}"
    return {"configurable": {"thread_id": resolved_thread_id}}


# 全局单例，供 frontend 直接导入
graph = build_graph()
