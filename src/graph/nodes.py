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
from src.memory.extractor import extract_memories_from_turn
from src.memory.store import format_memories_for_prompt, search_relevant_memories
from src.schemas.memory import (
    MemoryCandidate,
    MemoryQuery,
    MemoryWrite,
    MemoryWriteResult,
    coerce_metadata,
)
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
    "fetch_monthly_alarm_count": "alarm",
    "fetch_carbon_info": "monitor",
    "fetch_photovoltaic_monthly": "monitor",
    "fetch_photovoltaic_daily": "monitor",
    "fetch_energy_usage": "monitor",
    "fetch_device_rank": "monitor",
    "fetch_environment_params": "monitor",
    "fetch_efficiency_calendar": "monitor",
    "fetch_efficiency_detail": "monitor",
    "navigate_to_page": "general",
    "search_memory": "memory",
    "search_relevant_memory": "memory",
    "save_memory": "memory",
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


def _get_site_id(state: AgentState) -> str:
    """从 State 中提取站点 ID。

    Args:
        state: 当前 AgentState。

    Returns:
        站点 ID；缺省返回配置中的 default_site_id。
    """
    if state.get("site_id"):
        return state["site_id"] or settings.memory.default_site_id
    page_context = state.get("page_context")
    if page_context is not None:
        if hasattr(page_context, "site_id") and page_context.site_id:
            return page_context.site_id
        if isinstance(page_context, dict) and page_context.get("site_id"):
            return page_context["site_id"]
    return settings.memory.default_site_id


def _get_agent_id(state: AgentState) -> str:
    """从 State 中提取 Agent ID。

    Args:
        state: 当前 AgentState。

    Returns:
        Agent ID；缺省返回 main_graph。
    """
    return state.get("agent_id") or settings.memory.default_agent_id


def _inject_memory_context(state: AgentState, system_content: str) -> tuple[str, Dict[str, Any]]:
    """检索 L2 长期记忆并注入 system prompt。

    Args:
        state: 当前 AgentState。
        system_content: 原始 system prompt。

    Returns:
        注入后的 system prompt 与待合并 updates。
    """
    if not settings.memory.enabled:
        return system_content, {}

    try:
        result = search_relevant_memories(
            query=state.get("user_input", ""),
            agent_id=_get_agent_id(state),
            site_id=_get_site_id(state),
            thread_id=state.get("thread_id") or "unknown",
            limit=10,
        )
        if result.error:
            logger.warning(result.error)
            return system_content, {"memory_search_result": result}

        memory_context = format_memories_for_prompt(result.memories)
        if not memory_context:
            return system_content, {"memory_search_result": result}

        prompts = _load_prompts()
        hint = prompts.get("memory_injection_hint", {}).get("system", "")
        if hint:
            system_content += f"\n\n{hint}"
        system_content += f"\n\n## 用户历史偏好与长期记忆\n{memory_context}"
        return system_content, {
            "memory_context": memory_context,
            "memory_search_result": result,
        }
    except Exception as exc:
        logger.warning(f"memory injection skipped: {exc}")
        return system_content, {}


def cognitive_parser_node(state: AgentState) -> Dict[str, Any]:
    """意图解析节点：分析用户输入，决定调用哪些工具。

    Args:
        state: 当前 AgentState

    Returns:
        AgentState 更新字典（messages, 可选 intent_plan / error）
    """
    messages = list(state.get("messages", []))
    new_messages = []
    new_message_metadata = []
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

        system_content, memory_updates = _inject_memory_context(state, system_content)

        messages = [
            SystemMessage(content=system_content),
            HumanMessage(content=state.get("user_input", "")),
        ]
        new_messages = messages
        new_message_metadata = (
            _make_metadata("cognitive_parser", "system", 1)
            + _make_metadata("cognitive_parser", "user", 1)
        )
    else:
        memory_updates = {}
        user_input = (state.get("user_input") or "").strip()
        last_message = messages[-1] if messages else None
        is_tool_loop = isinstance(last_message, ToolMessage)
        is_same_pending_user = (
            isinstance(last_message, HumanMessage)
            and str(last_message.content).strip() == user_input
        )
        if user_input and not is_tool_loop and not is_same_pending_user:
            human_message = HumanMessage(content=state.get("user_input", ""))
            messages.append(human_message)
            new_messages.append(human_message)
            new_message_metadata = _make_metadata("cognitive_parser", "user", 1)

    try:
        llm = _get_llm(bind_tools=True)
        response: AIMessage = llm.invoke(messages)

        # Phase 7: 若 LLM 输出多个 tool_calls，自动构建 intent_plan
        updates: Dict[str, Any] = {
            "messages": [*new_messages, response],
            "message_metadata": (
                new_message_metadata + _make_metadata("cognitive_parser", "assistant", 1)
            ),
            **memory_updates,
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


def _legacy_keyword_memory_write(state: AgentState) -> Dict[str, Any]:
    """旧版关键词触发记忆写入，用作 demo/fallback。

    Args:
        state: 当前 AgentState。

    Returns:
        AgentState 更新字典。
    """
    user_input = (state.get("user_input") or "").strip()
    if not user_input:
        return {}

    trigger_words = ("记住", "以后", "下次", "默认")
    if not any(word in user_input for word in trigger_words):
        return {}
    if any(mark in user_input for mark in ("?", "？")):
        return {}
    retrievable_signals = (
        "当前",
        "今天",
        "昨日",
        "本月",
        "实时",
        "告警",
        "发电量",
        "用电量",
        "功率",
        "温度",
        "湿度",
        "COP",
        "SOC",
        "kWh",
        "kW",
    )
    if any(signal.lower() in user_input.lower() for signal in retrievable_signals):
        return {}

    try:
        from src.memory.store import get_memory_store

        agent_id = _get_agent_id(state)
        site_id = _get_site_id(state)
        metadata = coerce_metadata(
            {
                "memory_type": "user_preference",
                "source_thread_id": state.get("thread_id") or "unknown",
                "confidence": 0.75,
                "tags": ["explicit_user_preference"],
            },
            agent_id=agent_id,
            site_id=site_id,
        )
        request = MemoryWrite(
            content=user_input,
            agent_id=agent_id,
            site_id=site_id,
            scope="session_note",
            entity_id=state.get("thread_id") or "default",
            metadata=metadata,
        )
        result = get_memory_store().save(request)
        if result.error:
            logger.warning(result.error)
        return {"memory_write_result": result}
    except Exception as exc:
        logger.warning(f"memory manager skipped: {exc}")
        return {"memory_write_result": MemoryWriteResult(error=f"memory: {exc}")}


def _resolve_memory_scope(candidate: MemoryCandidate) -> str:
    """把记忆类型映射为 namespace scope。

    Args:
        candidate: 记忆候选。

    Returns:
        namespace scope。
    """
    scope_map = {
        "user_preference": "user_preference",
        "site_fact": "site",
        "safety_constraint": "safety_constraint",
        "decision_history": "decision_history",
        "device_state": "device_state",
    }
    return scope_map.get(candidate.memory_type, candidate.memory_type)


def _resolve_memory_entity_id(candidate: MemoryCandidate, state: AgentState, site_id: str) -> str:
    """根据记忆类型解析 namespace entity_id。

    Args:
        candidate: 记忆候选。
        state: 当前 AgentState。
        site_id: 当前站点 ID。

    Returns:
        namespace entity_id。
    """
    thread_id = state.get("thread_id") or "unknown"
    if candidate.memory_type == "user_preference":
        # TODO: 接入真实 user_id 后优先使用用户 ID；当前先用 thread_id 隔离用户偏好。
        return str(state.get("user_id") or thread_id or "default_user")
    if candidate.memory_type in {"site_fact", "safety_constraint", "device_state"}:
        return site_id
    if candidate.memory_type == "decision_history":
        return thread_id
    return thread_id


def _is_duplicate_memory(
    candidate: MemoryCandidate,
    agent_id: str,
    site_id: str,
    scope: str,
    entity_id: str,
) -> bool:
    """执行第一版完全文本重复判断。

    Args:
        candidate: 记忆候选。
        agent_id: 当前 Agent ID。
        site_id: 当前站点 ID。
        scope: namespace scope。
        entity_id: namespace entity_id。

    Returns:
        存在完全相同记忆时返回 True。
    """
    try:
        from src.memory.store import get_memory_store

        result = get_memory_store().search(
            MemoryQuery(
                query=candidate.content,
                agent_id=agent_id,
                site_id=site_id,
                scope=scope,
                entity_id=entity_id,
                memory_types=[candidate.memory_type],
                limit=20,
                include_expired=False,
            )
        )
        if result.error:
            logger.warning(result.error)
            return False
        return any(item.content.strip() == candidate.content.strip() for item in result.memories)
    except Exception as exc:
        logger.warning(f"memory duplicate check skipped: {exc}")
        return False


def _candidate_passes_quality_gate(candidate: MemoryCandidate) -> bool:
    """判断候选是否满足写入质量闸门。

    Args:
        candidate: 记忆候选。

    Returns:
        满足写入条件返回 True。
    """
    content = candidate.content.strip()
    if not candidate.should_save:
        return False
    if candidate.confidence < settings.memory.extract_min_confidence:
        return False
    if len(content) < 6:
        return False
    if candidate.source != "user_explicit" or candidate.retrievable:
        return False
    if candidate.memory_type == "device_state":
        return False
    if candidate.memory_type == "user_preference":
        return True
    if candidate.memory_type in {"site_fact", "safety_constraint", "decision_history"}:
        return candidate.user_confirmed
    return False


def memory_manager_node(state: AgentState) -> Dict[str, Any]:
    """长期记忆管理节点：按需写入 L2 记忆。

    Args:
        state: 当前 AgentState。

    Returns:
        AgentState 更新字典；写入失败只记录 memory_write_result，不阻断主流程。
    """
    if not settings.memory.enabled:
        return {}

    user_input = (state.get("user_input") or "").strip()
    if not user_input:
        return {}

    if not settings.memory.auto_extract_enabled:
        return _legacy_keyword_memory_write(state)

    try:
        from src.memory.store import get_memory_store

        prompts = _load_prompts()
        prompt = prompts.get("memory_extraction_hint", {}).get("system", "")
        agent_id = _get_agent_id(state)
        site_id = _get_site_id(state)
        thread_id = state.get("thread_id") or "unknown"
        extraction = extract_memories_from_turn(
            user_input=user_input,
            final_report=state.get("final_report", ""),
            agent_id=agent_id,
            site_id=site_id,
            thread_id=thread_id,
            prompt=prompt,
        )

        results = []
        for candidate in extraction.candidates[: settings.memory.max_memories_per_turn]:
            candidate.content = candidate.content.strip()
            if not _candidate_passes_quality_gate(candidate):
                continue

            scope = _resolve_memory_scope(candidate)
            entity_id = _resolve_memory_entity_id(candidate, state, site_id)
            if _is_duplicate_memory(candidate, agent_id, site_id, scope, entity_id):
                continue

            metadata = coerce_metadata(
                {
                    "memory_type": candidate.memory_type,
                    "source_thread_id": thread_id,
                    "confidence": candidate.confidence,
                    "ttl_seconds": candidate.ttl_seconds,
                    "tags": candidate.tags,
                },
                agent_id=agent_id,
                site_id=site_id,
            )
            request = MemoryWrite(
                content=candidate.content,
                agent_id=agent_id,
                site_id=site_id,
                scope=scope,
                entity_id=entity_id,
                metadata=metadata,
            )
            result = get_memory_store().save(request)
            if result.error:
                logger.warning(result.error)
            results.append(result)

        return {"memory_write_result": results[-1] if results else None}
    except Exception as exc:
        logger.warning(f"memory manager skipped: {exc}")
        return {"memory_write_result": MemoryWriteResult(error=f"memory: {exc}")}
