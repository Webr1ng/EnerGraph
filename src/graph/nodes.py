"""nodes — 决策层 Agent LangGraph 节点实现

所属层：graph
依赖：langchain_core, src.tools, src.config.settings
对接算法层：HVAC RAG / 福加运营数据 API（通过 Tools）
"""
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from src.config.settings import settings
from src.graph.state import AgentState
from src.tools import TOOL_REGISTRY, TOOL_SCHEMAS

logger = logging.getLogger(__name__)

# Prompts 通过 settings.prompts 统一加载（支持多文件）
_prompts: Dict[str, Any] = {}

# Phase 7: 工具名 → 意图类别映射
_TOOL_CATEGORY: Dict[str, str] = {
    "query_hvac_knowledge": "hvac",
    "fetch_cop_data": "monitor",
    "fetch_energy_summary": "monitor",
    "fetch_active_alarms": "alarm",
    "fetch_carbon_info": "monitor",
    "fetch_photovoltaic_monthly": "monitor",
    "fetch_photovoltaic_daily": "monitor",
    "fetch_energy_usage": "monitor",
    "fetch_device_rank": "monitor",
    "fetch_environment_params": "monitor",
    "fetch_efficiency_calendar": "monitor",
    "fetch_efficiency_detail": "monitor",
    "navigate_to_page": "general",
}

# 工具名 → AgentState 字段映射
_TOOL_FIELD_MAP: Dict[str, str] = {
    "query_hvac_knowledge": "hvac_knowledge",
}


def _make_metadata(node: str, role: str, count: int = 1) -> list:
    """为即将追加的消息生成 metadata 条目。

    Args:
        node: 产生消息的节点名（如 'cognitive_parser'）
        role: 消息角色（'system' / 'user' / 'assistant' / 'tool'）
        count: 生成的条目数量（与 messages 列表长度对应）

    Returns:
        metadata dict 列表，与 messages 一一对应
    """
    ts = datetime.now(timezone.utc).isoformat()
    return [{"timestamp": ts, "node": node, "role": role}] * count


def _load_prompts() -> Dict[str, Any]:
    """从 settings.prompts 获取 Prompt 字典（共享片段已由 settings 注入）。"""
    global _prompts
    if not _prompts:
        _prompts = settings.prompts or {}
    return _prompts


def _get_llm(bind_tools: bool = False) -> Any:
    """创建 LLM 实例，根据 LLM_PROVIDER 选择供应商。

    Args:
        bind_tools: 是否绑定 TOOL_SCHEMAS（function calling 用）

    Returns:
        ChatOpenAI / ChatAnthropic 实例（可选绑定 tools）
    """
    import os

    provider = os.getenv("LLM_PROVIDER", settings.model.provider).lower()
    model_name = settings.model.name
    temperature = settings.model.temperature

    if provider == "deepseek":
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(
            model=model_name,
            temperature=temperature,
            base_url="https://api.deepseek.com/v1",
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            streaming=True,
            extra_body={"thinking": {"type": "disabled"}},
        )
    elif provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        llm = ChatAnthropic(model=model_name, temperature=temperature, streaming=True)
    else:
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(model=model_name, temperature=temperature, streaming=True)

    return llm.bind_tools(TOOL_SCHEMAS) if bind_tools else llm


def _build_route_table_md() -> str:
    """从 routes.yaml 动态构建路由表 Markdown，注入到 system prompt 中。

    Returns:
        格式化的路由表 Markdown 字符串，按 category 分组。
    """
    routes_config = settings.routes
    accessible = routes_config.get("accessible_routes", [])

    if not accessible:
        return ""

    lines = ["\n## 可用路由表（福加能碳管理平台真实路由）\n"]

    # 按 category 分组
    from collections import OrderedDict
    categories: dict = OrderedDict()
    for route in accessible:
        cat = route.get("category", "其他")
        categories.setdefault(cat, []).append(route)

    for cat, routes in categories.items():
        lines.append(f"### {cat}类")
        lines.append("| 路由 | 页面名称 | 适用场景 |")
        lines.append("|------|---------|---------|")
        for r in routes:
            lines.append(f"| `{r['path']}` | {r['name']} | {r['description']} |")
        lines.append("")

    return "\n".join(lines)


def cognitive_parser_node(state: AgentState) -> Dict[str, Any]:
    """意图解析节点：分析用户输入，决定调用哪些工具。

    Args:
        state: 当前 AgentState

    Returns:
        AgentState 更新字典（messages, 可选 intent_plan / error）
    """
    messages = state.get("messages", [])
    if not messages:
        prompts = _load_prompts()
        system_content = prompts.get("cognitive_parser", {}).get("system", "")

        # 动态注入路由表（从 routes.yaml 读取，保持与代码侧同步）
        route_table = _build_route_table_md()
        if route_table:
            system_content += route_table

        # 注入当前日期
        from datetime import datetime
        current_date = datetime.now().strftime("%Y-%m-%d")
        system_content += f"\n\n## 当前时间\n当前日期：{current_date}"

        page_context = state.get("page_context")
        if page_context is not None:
            if hasattr(page_context, "current_route"):
                route = page_context.current_route
                site_id = page_context.site_id
            else:
                route = page_context.get("current_route", "/")
                site_id = page_context.get("site_id")
            system_content += f"\n\n## 当前页面上下文\n- 当前路由：{route}\n- 站点 ID：{site_id or '未指定'}"

        messages = [
            SystemMessage(content=system_content),
            HumanMessage(content=state.get("user_input", "")),
        ]

    try:
        llm = _get_llm(bind_tools=True)
        response: AIMessage = llm.invoke(messages)

        # Phase 7: 若 LLM 输出多个 tool_calls，自动构建 intent_plan
        updates: Dict[str, Any] = {
            "messages": [*messages, response],
            "message_metadata": (
                _make_metadata("cognitive_parser", "system", 1)
                + _make_metadata("cognitive_parser", "user", 1)
                + _make_metadata("cognitive_parser", "assistant", 1)
            ),
        }
        tool_calls = getattr(response, "tool_calls", None) or []
        if len(tool_calls) > 1:
            from src.schemas.v3_engine import IntentItem
            intent_plan = [
                IntentItem(
                    id=i + 1,
                    description=f"调用 {tc['name']}",
                    category=_TOOL_CATEGORY.get(tc["name"], "general"),
                    status="pending",
                )
                for i, tc in enumerate(tool_calls)
            ]
            updates["intent_plan"] = intent_plan
            logger.info(f"多意图识别：{len(intent_plan)} 个意图")

        return updates
    except Exception as e:
        logger.error(f"cognitive_parser_node 失败: {e}")
        return {
            "messages": messages,
            "message_metadata": _make_metadata("cognitive_parser", "system", 1)
                              + _make_metadata("cognitive_parser", "user", 1),
            "error": str(e),
        }


def v3_engine_router_node(state: AgentState) -> Dict[str, Any]:
    """引擎调度节点：执行 LLM 选择的工具，通过 BaseSkill 统一调度。

    Args:
        state: 当前 AgentState

    Returns:
        AgentState 更新字典（messages + 工具结果字段 + Skill 更新字段）
    """
    messages = state.get("messages", [])
    last: AIMessage = messages[-1]

    tool_messages = []
    tool_results: list = []  # [(name, result, args), ...] 供 Skill 调度使用
    updates: Dict[str, Any] = {}

    for tool_call in last.tool_calls:
        name = tool_call["name"]
        args = tool_call["args"]

        if name not in TOOL_REGISTRY:
            result = {"error": f"工具 '{name}' 不存在"}
        else:
            try:
                result = TOOL_REGISTRY[name](**args)
            except Exception as e:
                logger.error(f"工具 {name} 执行失败: {e}")
                result = {"error": str(e)}

        tool_results.append((name, result, args))

        # 将结果写入对应 state 字段
        if name in _TOOL_FIELD_MAP and "error" not in result:
            updates[_TOOL_FIELD_MAP[name]] = result

        tool_messages.append(
            ToolMessage(
                content=json.dumps(result, ensure_ascii=False),
                tool_call_id=tool_call["id"],
            )
        )

    # Skill 统一调度：遍历注册表，匹配本轮工具调用
    from src.skills import get_matched_skills
    tool_names = [name for name, _, _ in tool_results]
    for skill in get_matched_skills(tool_names):
        state_for_skill = {**state, **updates}
        state_for_skill = skill.before_execute(state_for_skill)
        skill_updates = skill.execute(tool_results, state_for_skill)
        skill_updates = skill.after_execute(state_for_skill, skill_updates)
        updates.update(skill_updates)
        logger.info(f"Skill {skill.name} 执行完毕，更新字段: {list(skill_updates.keys())}")

    return {
        "messages": tool_messages,
        "message_metadata": _make_metadata("v3_engine_router", "tool", len(tool_messages)),
        **updates,
    }


def interpreter_generator_node(state: AgentState) -> Dict[str, Any]:
    """报告生成节点：将物理数据转化为多维 Markdown 解释报告。

    Args:
        state: 当前 AgentState

    Returns:
        AgentState 更新字典（final_report, 可选 error）
    """
    messages = state.get("messages", [])
    last = messages[-1] if messages else None

    # LLM 直接输出文本（无工具调用）时直接使用
    if isinstance(last, AIMessage) and not getattr(last, "tool_calls", None):
        return {"final_report": last.content}

    # 否则用物理数据重新生成报告
    prompts = _load_prompts()
    system_content = prompts.get("interpreter_generator", {}).get("system", "")

    # Phase 3: 应用 HVAC Skill 上下文指令（拒答 / 引用来源）
    hvac_hint = state.get("hvac_context_hint")
    context_override = None
    if hvac_hint:
        system_suffix = hvac_hint.get("system_suffix", "")
        if system_suffix:
            system_content += system_suffix
        context_override = hvac_hint.get("context_override")

    # Phase 7: 注入多意图执行计划，引导分段报告
    intent_plan = state.get("intent_plan")
    if intent_plan:
        def _intent_line(i):
            if isinstance(i, dict):
                return f"- 意图 {i.get('id', '?')}: {i.get('description', '')} ({i.get('status', 'pending')})"
            return f"- 意图 {i.id}: {i.description} ({i.status})"
        intent_summary = "\n".join(_intent_line(i) for i in intent_plan)
        system_content += f"\n\n## 本次处理的用户意图\n{intent_summary}"

    # 构建上下文数据
    hvac_data = state.get("hvac_knowledge")
    if context_override is not None:
        # 拒答模式：替换检索内容，避免 LLM 看到无关检索结果
        hvac_data = context_override

    context_data: Dict[str, Any] = {"hvac_knowledge": hvac_data}
    constraints = state.get("constraints")
    if constraints is not None:
        context_data["constraints"] = constraints
    physics_verification = state.get("physics_verification")
    if physics_verification is not None:
        context_data["physics_verification"] = physics_verification

    context = json.dumps(context_data, ensure_ascii=False, indent=2)

    try:
        llm = _get_llm()
        response = llm.invoke([
            SystemMessage(content=system_content),
            HumanMessage(content=f"以下是工具层返回的数据，请生成报告：\n{context}"),
        ])
        return {"final_report": response.content}
    except Exception as e:
        logger.error(f"interpreter_generator_node 失败: {e}")
        return {"final_report": f"报告生成失败：{e}", "error": str(e)}
