"""skills — 业务技能注册表

所属层：skills（Tools 之上的业务推理层）
依赖：src.skills.*
对接算法层：N/A（由各 Skill 内部编排 Tools）

Skills 与 Tools 的分工：
  Tools = 原子执行层（确定性函数，强类型 I/O，不含 Prompt）
  Skills = 业务推理层（专属 Prompt + SOP 流程 + Tools 编排）

v3_engine_router 根据本轮 Tool 名称调用 get_matched_skills()，
再通过匹配到的 Skill 处理工具结果与状态更新。
"""
from typing import Dict, Optional

from src.skills.base_skill import BaseSkill
from src.skills.hvac_expert_skill import HVACExpertSkill
from src.skills.document_knowledge_skill import DocumentKnowledgeSkill
from src.skills.energy_dispatch_skill import EnergyDispatchSkill
from src.skills.ui_router_skill import UIRouterSkill
from src.skills.v3_interpreter_skill import V3InterpreterSkill

# 技能注册表：key = 技能名，value = 技能实例
SKILL_REGISTRY: Dict[str, BaseSkill] = {
    "hvac_expert": HVACExpertSkill(),
    "document_knowledge": DocumentKnowledgeSkill(),
    "energy_dispatch": EnergyDispatchSkill(),
    "ui_router": UIRouterSkill(),
    "v3_interpreter": V3InterpreterSkill(),
}

# Skill.description 是描述的单点真相，避免注册表与类属性重复维护后漂移。
SKILL_DESCRIPTIONS = {
    name: skill.description
    for name, skill in SKILL_REGISTRY.items()
}


def get_skill(name: str) -> Optional[BaseSkill]:
    """工厂函数：按名称获取 Skill 实例。

    Args:
        name: 技能名（对应 SKILL_REGISTRY 的 key）

    Returns:
        BaseSkill 实例，不存在时返回 None
    """
    return SKILL_REGISTRY.get(name)


def get_matched_skills(tool_names: list) -> list:
    """根据本轮工具调用，返回匹配的 Skill 实例列表。

    Args:
        tool_names: 本轮 LLM 调用的工具名列表

    Returns:
        匹配的 BaseSkill 实例列表
    """
    matched = []
    for skill in SKILL_REGISTRY.values():
        if any(skill.has_tool(t) for t in tool_names):
            matched.append(skill)
    return matched
