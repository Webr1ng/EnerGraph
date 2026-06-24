"""agents — 多智能体注册表

所属层：graph/agents
依赖：src.graph.agents.*
对接算法层：由各 Agent 实现

主图通过 AGENT_REGISTRY 动态加载所有 Agent 子图。
新增 Agent 只需在此注册，主图无需改动。
"""
import logging
from typing import Dict, Optional

from src.graph.agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)

# Agent 注册表：key = agent 名称，value = Agent 实例
AGENT_REGISTRY: Dict[str, BaseAgent] = {}


def register_agent(agent: BaseAgent) -> None:
    """注册 Agent 到全局注册表"""
    AGENT_REGISTRY[agent.name] = agent


def get_agent(name: str) -> Optional[BaseAgent]:
    """按名称获取 Agent 实例"""
    return AGENT_REGISTRY.get(name)


def get_agent_descriptions() -> Dict[str, str]:
    """获取所有 Agent 的描述（供 cognitive_parser 意图识别）"""
    return {name: agent.description for name, agent in AGENT_REGISTRY.items()}


# 延迟导入避免循环依赖
def _register_all_agents():
    """注册所有可用 Agent（在模块加载时调用）"""
    try:
        from src.graph.agents.hvac_expert.agent import HVACExpertAgent
        register_agent(HVACExpertAgent())
    except ImportError as e:
        logger.warning("HVACExpertAgent 注册失败: %s", e)

    try:
        from src.graph.agents.ui_router.agent import UIRouterAgent
        register_agent(UIRouterAgent())
    except ImportError as e:
        logger.warning("UIRouterAgent 注册失败: %s", e)

    try:
        from src.graph.agents.powerai.agent import PowerAIAgent
        register_agent(PowerAIAgent())
    except ImportError as e:
        logger.warning("PowerAIAgent 注册失败: %s", e)


_register_all_agents()
