"""nodes — 决策层 Agent LangGraph 节点实现

所属层：graph
依赖：langchain_core, src.tools, src.config.settings
对接算法层：HVAC RAG / 福加运营数据 API（通过 Tools）
"""
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from src.config.settings import settings
from src.graph.state import AgentState
from src.memory.extractor import extract_memories_from_turn
from src.memory.store import format_memories_for_prompt, search_relevant_memories
from src.schemas.memory import (
    MemoryCandidate,
    MemoryItem,
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


def _sanitize_report(text: str) -> str:
    """后处理最终回答文本：剔除 LLM 偶发的违规输出。

    Args:
        text: LLM 生成的原文。

    Returns:
        清理后的安全文本。
    """
    if not text:
        return text

    # 1) 剔除 Markdown 删除线（~~text~~），连同内容一并移除（避免"价格是100200元"歧义）
    text = re.sub(r"~~[^~]+~~", "", text)

    # 2) 数字间波浪号改为「至」（如 100~200 → 100至200）
    text = re.sub(r"(\d)\s*~\s*(\d)", r"\1至\2", text)

    # 3) 剔除以"暂缺接口"或"暂无数据"兜底的违禁跳转动词（已为您跳转/打开/进入/切换）
    forbidden_redirect = [
        r"已为您跳转(?:至|到)?[^。\n]*[。]?",
        r"已为您打开[^。\n]*[。]?",
        r"已进入[^。\n]*页面[^。\n]*[。]?",
        r"已切换到[^。\n]*[。]?",
    ]
    for pattern in forbidden_redirect:
        text = re.sub(pattern, "", text)

    # 4) 清理多余空行（连续 3+ 换行 → 2 换行）
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


# 预编译：固定跳转话术（用作无跳转时切除）
_RE_FIXED_JUMP_PHRASE = re.compile(
    r"\n*\s*详细信息请点击下方链接跳转。[ \t]*", re.MULTILINE
)


def _strip_redirect_if_no_jump(text: str, state: AgentState) -> str:
    """若无 pending_actions，切除 LLM 误加的固定跳转话术。

    LLM 偶在纯知识问答（仅调 query_hvac_knowledge）后仍输出固定话术，
    因提示"有跳转时用此句收尾"被误解为"调了工具就用"。此函数根据实际是否
    生成了跳转动作做确定性切除。
    """
    pending = state.get("pending_actions") or []
    if pending:
        return text
    return _RE_FIXED_JUMP_PHRASE.sub("", text).strip()


def _load_prompts() -> Dict[str, Any]:
    """从 settings.prompts 获取 Prompt 字典（共享片段已由 settings 注入）。"""
    global _prompts
    if not _prompts:
        _prompts = settings.prompts or {}
    return _prompts


def _get_llm(bind_tools: bool = False) -> Any:
    """创建 LLM 实例（统一走 src.config.llm.get_llm，按 LLM_PROVIDER 切换供应商）。

    Args:
        bind_tools: 是否绑定 TOOL_SCHEMAS（function calling 用）

    Returns:
        ChatOpenAI / ChatAnthropic 实例（可选绑定 tools）
    """
    from src.config.llm import get_llm

    llm = get_llm(streaming=True)
    if not bind_tools:
        return llm
    return llm.bind_tools(_get_agent_tool_schemas())


def _get_agent_tool_schemas() -> list[Dict[str, Any]]:
    """返回主 Agent 可绑定的工具 schema，排除直接记忆写入工具。"""
    return [schema for schema in TOOL_SCHEMAS if schema.get("name") != "save_memory"]


def _new_turn_state_resets() -> Dict[str, Any]:
    """返回新用户轮次需要清空的临时业务状态。

    Returns:
        仅在新用户消息进入时写回 AgentState 的重置字段。
    """
    return {
        "constraints": None,
        "physics_verification": None,
        "hvac_knowledge": None,
        "hvac_context_hint": None,
        "intent_plan": None,
        "context": None,
        "memory_context": None,
        "memory_search_result": None,
        "memory_write_result": None,
        "memory_feedback": None,
        "final_report": "",
        "error": None,
        "pending_actions": [],
        "pending_data_cards": [],
    }


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


def _get_user_id(state: AgentState) -> str:
    """获取稳定用户 ID；演示环境统一使用 default_user。"""
    return state.get("user_id") or "default_user"


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
            user_id=_get_user_id(state),
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


def _is_memory_mutation_query(user_input: str) -> bool:
    """判断用户是否在修改、取消或删除长期记忆。"""
    normalized = user_input.strip().lower()
    mutation_actions = ("更新", "修改", "改成", "改为", "调整", "替换", "覆盖", "取消", "删除", "清除", "忘记")
    memory_targets = ("偏好", "记忆", "习惯", "记住", "保存", "记录")
    return any(action in normalized for action in mutation_actions) and any(
        target in normalized for target in memory_targets
    )


def is_explicit_memory_write_request(user_input: str) -> bool:
    """判断用户是否明确要求保存长期记忆。

    Args:
        user_input: 用户原始输入。

    Returns:
        明确要求写入或更新记忆时返回 True。
    """
    normalized = user_input.strip().lower()
    question_signals = ("什么", "哪些", "是否", "有没有", "吗", "呢", "？", "?")
    if any(signal in normalized for signal in question_signals):
        return False
    direct_write_actions = ("记住", "记下", "请记录", "保存这个", "保存为偏好")
    preference_signals = ("偏好", "希望", "回答", "报告", "分析", "展示", "关注", "使用")
    future_preference = any(action in normalized for action in ("以后", "下次", "默认")) and any(
        signal in normalized for signal in preference_signals
    )
    return (
        _is_memory_mutation_query(user_input)
        or any(action in normalized for action in direct_write_actions)
        or future_preference
    )


def _is_memory_recall_query(user_input: str) -> bool:
    """判断用户是否在显式查询已保存的长期记忆。"""
    normalized = user_input.strip().lower()
    if _is_memory_mutation_query(user_input):
        return False
    if is_explicit_memory_write_request(user_input):
        return False
    recall_phrases = (
        "长期偏好",
        "长期记忆",
        "保存了哪些",
        "保存的偏好",
        "记住了什么",
        "记得我的",
        "我的偏好",
    )
    if any(phrase in normalized for phrase in recall_phrases):
        return True
    recall_actions = ("记得", "记住", "保存", "记录", "有哪些", "有什么", "哪些", "什么")
    return "偏好" in normalized and any(action in normalized for action in recall_actions)


def _format_memory_recall_answer(result: Any, user_input: str) -> str:
    """把结构化长期记忆结果直接格式化为回答，避免误路由业务 Tool。"""
    memories = list(getattr(result, "memories", []) or []) if result is not None else []
    if "偏好" in user_input:
        memories = [item for item in memories if item.metadata.memory_type == "user_preference"]
    if not memories:
        return "当前没有检索到已保存的长期偏好。" if "偏好" in user_input else "当前没有检索到已保存的长期记忆。"

    title = "目前保存的长期偏好" if "偏好" in user_input else "目前保存的长期记忆"
    lines = [f"{title}共 {len(memories)} 条："]
    lines.extend(f"{index}. {item.content}" for index, item in enumerate(memories, start=1))
    return "\n".join(lines)


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
    turn_resets: Dict[str, Any] = {}
    if not messages:
        turn_resets = _new_turn_state_resets()
        prompts = _load_prompts()
        system_content = prompts.get("cognitive_parser", {}).get("system", "")

        visualization_hint = prompts.get("data_visualization_hint", {}).get("system", "")
        if visualization_hint:
            system_content += f"\n\n{visualization_hint}"

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
            resolved_site = site_id or state.get("site_id") or settings.memory.default_site_id
            system_content += f"\n\n## 当前页面上下文\n- 当前路由：{route}\n- 站点 ID：{resolved_site}"

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
            turn_resets = _new_turn_state_resets()
            memory_system, memory_updates = _inject_memory_context(state, "")
            if memory_system.strip():
                memory_message = SystemMessage(content=memory_system.strip())
                messages.append(memory_message)
                new_messages.append(memory_message)
                new_message_metadata += _make_metadata("cognitive_parser", "system", 1)
            human_message = HumanMessage(content=state.get("user_input", ""))
            messages.append(human_message)
            new_messages.append(human_message)
            new_message_metadata += _make_metadata("cognitive_parser", "user", 1)

    try:
        user_input = (state.get("user_input") or "").strip()
        if _is_memory_recall_query(user_input):
            result = memory_updates.get("memory_search_result")
            recall_response = AIMessage(content=_format_memory_recall_answer(result, user_input))
            return {
                "messages": [*new_messages, recall_response],
                "message_metadata": (
                    new_message_metadata + _make_metadata("cognitive_parser", "assistant", 1)
                ),
                **turn_resets,
                **memory_updates,
            }
        llm = _get_llm(bind_tools=True)
        response: AIMessage = llm.invoke(messages)

        # Phase 7: 若 LLM 输出多个 tool_calls，自动构建 intent_plan
        updates: Dict[str, Any] = {
            "messages": [*new_messages, response],
            "message_metadata": (
                new_message_metadata + _make_metadata("cognitive_parser", "assistant", 1)
            ),
            **turn_resets,
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
        return {"final_report": _strip_redirect_if_no_jump(_sanitize_report(last.content), state)}

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
        return {"final_report": _strip_redirect_if_no_jump(_sanitize_report(response.content), state)}
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
            scope="user_preference",
            entity_id=_get_user_id(state),
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
        return _get_user_id(state)
    if candidate.memory_type in {"site_fact", "safety_constraint", "device_state"}:
        return site_id
    if candidate.memory_type == "decision_history":
        return thread_id
    return thread_id


def _find_duplicate_memory(
    candidate: MemoryCandidate,
    agent_id: str,
    site_id: str,
    scope: str,
    entity_id: str,
) -> Optional[MemoryItem]:
    """查找正文完全相同的现有记忆。

    Args:
        candidate: 记忆候选。
        agent_id: 当前 Agent ID。
        site_id: 当前站点 ID。
        scope: namespace scope。
        entity_id: namespace entity_id。

    Returns:
        存在时返回现有 MemoryItem，否则返回 None。
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
            return None
        return next(
            (
                item
                for item in result.memories
                if item.content.strip() == candidate.content.strip()
            ),
            None,
        )
    except Exception as exc:
        logger.warning(f"memory duplicate check skipped: {exc}")
        return None


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
        return bool(candidate.memory_key.strip())
    if candidate.memory_type in {"site_fact", "safety_constraint", "decision_history"}:
        return candidate.user_confirmed
    return False


def _is_response_format_preference(user_input: str) -> bool:
    """判断用户是否明确表达长期回答格式偏好。

    Args:
        user_input: 用户原始输入。

    Returns:
        同时命中长期表达、回答行为和格式属性时返回 True。
    """
    normalized = user_input.strip().lower()
    long_term_signals = ("以后", "下次", "默认")
    response_signals = ("回答", "报告", "展示", "输出")
    format_signals = (
        "顺序",
        "格式",
        "详细",
        "简洁",
        "表格",
        "图表",
        "先",
        "最后",
        "再给",
        "口径",
    )
    return (
        any(signal in normalized for signal in long_term_signals)
        and any(signal in normalized for signal in response_signals)
        and any(signal in normalized for signal in format_signals)
    )


def _response_preference_memory_key(user_input: str) -> str:
    """为回答格式偏好生成稳定语义键。

    Args:
        user_input: 用户原始输入。

    Returns:
        由业务领域和格式维度组成的稳定 memory_key。
    """
    normalized = user_input.strip().lower()
    domain = "general"
    if "能耗" in normalized or "用能" in normalized:
        domain = "energy_analysis"
    elif "cop" in normalized:
        domain = "cop"
    elif "光伏" in normalized:
        domain = "photovoltaic"

    if any(signal in normalized for signal in ("顺序", "先", "最后", "再给")):
        aspect = "report_order"
    elif any(signal in normalized for signal in ("表格", "图表", "格式", "展示", "输出")):
        aspect = "response_format"
    else:
        aspect = "response_style"
    return f"{domain}_{aspect}"


def _response_preference_content(user_input: str) -> str:
    """清理显式保存前缀，得到可独立理解的偏好正文。

    Args:
        user_input: 用户原始输入。

    Returns:
        去除保存指令前缀后的偏好正文。
    """
    content = user_input.strip()
    prefixes = (
        "请记住我的回答格式偏好：",
        "请记住我的偏好：",
        "请记住：",
        "请记住",
        "请保存为偏好：",
    )
    for prefix in prefixes:
        if content.startswith(prefix):
            content = content[len(prefix):].strip()
            break
    return content


def _correct_response_preference_candidates(
    candidates: list[MemoryCandidate],
    user_input: str,
) -> list[MemoryCandidate]:
    """对被误判为可查询数据的长期回答格式偏好做确定性纠偏。

    Args:
        candidates: LLM 抽取出的原始候选。
        user_input: 用户原始输入。

    Returns:
        正常候选保持不变；严格命中时返回纠偏或补建后的候选列表。
    """
    if not _is_response_format_preference(user_input):
        return candidates

    base = next(
        (
            candidate
            for candidate in candidates
            if candidate.memory_type == "user_preference"
            or _is_response_format_preference(candidate.content)
        ),
        candidates[0] if candidates else None,
    )
    if (
        base is not None
        and base.memory_type == "user_preference"
        and base.should_save
        and not base.retrievable
    ):
        return candidates

    content = (
        base.content.strip()
        if base is not None
        and base.memory_type == "user_preference"
        and base.content.strip()
        else _response_preference_content(user_input)
    )
    corrected = MemoryCandidate(
        should_save=True,
        content=content,
        memory_type="user_preference",
        confidence=max(base.confidence if base is not None else 0.0, 0.9),
        source="user_explicit",
        retrievable=False,
        user_confirmed=True,
        memory_key=_response_preference_memory_key(user_input),
        ttl_seconds=None,
        tags=list(dict.fromkeys([*(base.tags if base is not None else []), "response_preference"])),
        reason="代码层确认用户明确表达长期回答格式偏好",
    )
    remaining = [candidate for candidate in candidates if candidate is not base]
    return [corrected, *remaining]


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

        candidates = _correct_response_preference_candidates(
            list(extraction.candidates),
            user_input,
        )
        results = []
        for candidate in candidates[: settings.memory.max_memories_per_turn]:
            candidate.content = candidate.content.strip()
            if not _candidate_passes_quality_gate(candidate):
                continue

            scope = _resolve_memory_scope(candidate)
            entity_id = _resolve_memory_entity_id(candidate, state, site_id)
            duplicate = _find_duplicate_memory(candidate, agent_id, site_id, scope, entity_id)
            if duplicate is not None:
                results.append(
                    MemoryWriteResult(memory=duplicate, namespace=duplicate.namespace)
                )
                continue

            metadata = coerce_metadata(
                {
                    "memory_type": candidate.memory_type,
                    "source_thread_id": thread_id,
                    "confidence": candidate.confidence,
                    "ttl_seconds": candidate.ttl_seconds,
                    "tags": [
                        *candidate.tags,
                        *(
                            [f"memory_key:{candidate.memory_key.strip()}"]
                            if candidate.memory_key.strip()
                            else []
                        ),
                    ],
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
            if candidate.memory_key.strip():
                result = get_memory_store().upsert_by_tag(
                    request,
                    f"memory_key:{candidate.memory_key.strip()}",
                )
            else:
                result = get_memory_store().save(request)
            if result.error:
                logger.warning(result.error)
            results.append(result)

        updates: Dict[str, Any] = {
            "memory_write_result": results[-1] if results else None,
        }
        preference_result = next(
            (
                result
                for result in reversed(results)
                if result.memory is not None
                and result.memory.metadata.memory_type == "user_preference"
            ),
            None,
        )
        if is_explicit_memory_write_request(user_input) and preference_result is not None:
            action = "更新" if _is_memory_mutation_query(user_input) else "保存"
            preference_memory = preference_result.memory
            if preference_memory is None:
                raise RuntimeError("preference memory result is unexpectedly empty")
            feedback = f"已{action}长期偏好：{preference_memory.content}"
            updates["memory_feedback"] = feedback
            updates["final_report"] = feedback
        elif is_explicit_memory_write_request(user_input) and results:
            saved = results[-1].memory
            feedback = f"已保存长期记忆：{saved.content}" if saved is not None else "长期记忆写入未完成。"
            updates["memory_feedback"] = feedback
            updates["final_report"] = feedback
        elif is_explicit_memory_write_request(user_input) and not results:
            feedback = (
                "未写入长期记忆：该内容未通过长期记忆准入规则。"
                "可通过工具重新查询的运营数据、实时设备状态和普通查询请求不会长期保存。"
            )
            updates["memory_feedback"] = feedback
            updates["final_report"] = feedback
        return updates
    except Exception as exc:
        logger.warning(f"memory manager skipped: {exc}")
        return {"memory_write_result": MemoryWriteResult(error=f"memory: {exc}")}
