"""base_agent — 多智能体 Subgraph 基类

所属层：graph/agents
依赖：langgraph, typing, src.config.settings
对接算法层：N/A（由子类 Agent 实现）

BaseAgent 定义统一接口：
  - build_graph(): 返回编译后的 StateGraph
  - state_schema: 子图专属 State TypedDict
  - 所有 Agent 通过主图统一调度，输入/输出标准化
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, Type
from typing_extensions import TypedDict
from langgraph.graph import StateGraph

from src.config.settings import settings


class BaseAgentState(TypedDict, total=False):
    """Agent 子图的基础状态（所有子图必须包含的字段）"""
    user_input: str
    final_report: str
    error: str


class BaseAgent(ABC):
    """多智能体 Subgraph 抽象基类

    每个 Agent（HVAC、PowerAI、碳管理等）继承此类，实现独立的 StateGraph。
    主图通过 agent_dispatcher 路由到对应子图，子图返回 final_report。
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Agent 名称（用于注册表 key，如 'hvac_expert', 'powerai'）"""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Agent 功能描述（供 cognitive_parser 意图识别）"""
        pass

    @property
    @abstractmethod
    def state_schema(self) -> Type[TypedDict]:
        """子图专属 State TypedDict（必须继承 BaseAgentState）"""
        pass

    @abstractmethod
    def build_graph(self) -> StateGraph:
        """构建并编译子图

        Returns:
            编译后的 StateGraph（已调用 .compile()）
        """
        pass

    def memory_namespace(
        self,
        site_id: str = "",
        scope: str = "session_note",
        entity_id: str = "default",
    ) -> list[str]:
        """返回当前 Agent 默认长期记忆 namespace。

        Args:
            site_id: 站点 ID；为空时使用配置默认值。
            scope: 记忆范围。
            entity_id: 记忆实体 ID。

        Returns:
            namespace 字符串列表，默认包含 prefix/env/site/agent/scope/entity。
        """
        return [
            settings.memory.namespace_prefix,
            settings.memory.env,
            site_id or settings.memory.default_site_id,
            self.name,
            scope,
            entity_id,
        ]

    def transform_input(self, main_state: Dict[str, Any]) -> Dict[str, Any]:
        """主图 State → 子图 State 转换（可选覆盖）

        默认只传递 user_input 和 page_context，子类可覆盖此方法传递更多字段。

        Args:
            main_state: 主图的 AgentState

        Returns:
            子图的初始 State
        """
        return {
            "user_input": main_state.get("user_input", ""),
            "page_context": main_state.get("page_context"),
            "thread_id": main_state.get("thread_id"),
            "agent_id": self.name,
            "site_id": main_state.get("site_id"),
        }

    def transform_output(self, subgraph_state: Dict[str, Any]) -> Dict[str, Any]:
        """子图 State → 主图 State 转换（可选覆盖）

        默认只传递 final_report 和 pending_actions，子类可覆盖此方法传递更多字段。

        Args:
            subgraph_state: 子图执行完毕后的 State

        Returns:
            需要合并回主图的字段
        """
        updates = {"final_report": subgraph_state.get("final_report", "")}

        # 传递 pending_actions（UI 导航信号）
        if "pending_actions" in subgraph_state:
            updates["pending_actions"] = subgraph_state["pending_actions"]

        # 传递错误信息
        if "error" in subgraph_state:
            updates["error"] = subgraph_state["error"]

        return updates
