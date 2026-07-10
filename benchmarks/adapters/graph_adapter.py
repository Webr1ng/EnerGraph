"""graph_adapter — LangGraph 入口的 Eval Adapter 边界

所属层：tests
依赖：benchmarks.adapters.base, src.graph.builder
对接算法层：N/A
"""
from contextlib import contextmanager
from typing import Any, Callable, Optional

from benchmarks.adapters.base import AdapterResponse, BaseAdapter
from benchmarks.shared.config_models import EvalRunConfig
from benchmarks.shared.result_models import EvalCase, ToolCallRecord


_CLARIFICATION_SIGNALS = (
    "请明确", "请具体", "请问您", "请提供", "请告诉我", "您想查看哪方面", "请选择",
    "站点 ID", "站点ID", "目标站点", "没有检索到站点信息", "无法确定站点",
    "需要您补充", "补充站点", "补充一下", "数据类型", "时间范围",
)


def _is_clarification_answer(answer: str) -> bool:
    """判断无 Tool 回答是否是在请求用户补充关键信息。"""
    return any(signal in answer for signal in _CLARIFICATION_SIGNALS)


def _assistant_text(message: Any) -> str:
    """仅从 assistant/AI 消息提取可作为最终回答的文本。"""
    message_type = getattr(message, "type", "")
    class_name = message.__class__.__name__
    if message_type not in {"ai", "assistant"} and class_name not in {"AIMessage", "AssistantMessage"}:
        return ""
    if getattr(message, "tool_calls", None):
        return ""
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content.strip()
    return ""


def _apply_eval_runtime_overrides(config: EvalRunConfig) -> None:
    """按 Eval 后端配置隔离项目运行时，避免本地 .env 污染评测。"""
    if config.store.kind != "inmemory":
        return

    from src.config.settings import settings

    settings.memory.enabled = False
    settings.memory.use_postgres_store = False
    settings.memory.demo_file_store_enabled = False
    settings.memory.auto_extract_enabled = False


def _mock_tool_result(tool_name: str, case: EvalCase, arguments: dict[str, Any]) -> dict[str, Any]:
    """生成 Standard Mock Tool 结果，避免真实 Graph 触达产品外部依赖。"""
    site_id = str(arguments.get("site_id") or case.input.site_id)
    result = {
        "mock": True,
        "tool": tool_name,
        "site_id": site_id,
        "message": f"eval mock result for {tool_name}",
    }
    if tool_name == "query_hvac_knowledge":
        return {
            **result,
            "answer": f"模拟 HVAC 知识库结果：{arguments.get('question') or case.input.user_message}",
            "sources": [{"doc_id": "eval_mock_hvac_001", "title": "Eval Mock HVAC Source"}],
            "low_confidence": False,
        }
    if tool_name == "navigate_to_page":
        route = str(arguments.get("route") or "/analysis/consumption-panel")
        return {
            **result,
            "route": route,
            "name": "Eval Mock 页面",
            "action": {"type": "navigate", "route": route, "name": "Eval Mock 页面"},
        }
    if tool_name == "export_data_table":
        rows = arguments.get("rows") or [{"site_id": site_id, "value": 1.0}]
        columns = arguments.get("columns") or [{"key": "value", "label": "模拟值", "unit": "kWh"}]
        return {
            **result,
            "task_id": f"eval_mock_{case.case_id}",
            "download_url": f"/export/eval_mock_{case.case_id}",
            "columns": columns,
            "rows": rows,
        }
    if tool_name in {"search_memory", "search_relevant_memory"}:
        return {**result, "items": [], "query": arguments.get("query", "")}
    if tool_name == "save_memory":
        return {**result, "saved": True, "memory_id": f"eval_mock_{case.case_id}"}
    if tool_name == "parse_business_intent":
        return {**result, "intent": "energy_dispatch", "constraints": []}
    if tool_name == "fetch_energy_summary":
        date = str(arguments.get("date") or "2026-07-10")
        return {
            **result,
            "date": date,
            "total_consumption_kwh": 4083.5,
            "pv_generation_kwh": 1186.2,
            "grid_import_kwh": 2960.4,
            "storage_charge_kwh": 380.0,
            "storage_discharge_kwh": 312.0,
            "peak_load_kw": 612.8,
            "avg_load_kw": 170.15,
            "carbon_reduction_kg": 676.13,
        }
    if tool_name == "fetch_efficiency_detail":
        param_name = str(arguments.get("param_name") or "水系统平均COP")
        value = 9.1 if "COP" in param_name and "SCOP" not in param_name else 7.6
        return {**result, "param_name": param_name, "value": value, "unit": ""}
    if tool_name == "fetch_energy_range":
        return {
            **result,
            "start_date": arguments.get("start_date", "2026-07-04"),
            "end_date": arguments.get("end_date", "2026-07-10"),
            "total_days": 2,
            "items": [
                {"site_id": site_id, "date": "2026-07-09", "total_consumption_kwh": 4012.3},
                {"site_id": site_id, "date": "2026-07-10", "total_consumption_kwh": 4083.5},
            ],
        }
    if tool_name in {"fetch_active_alarms", "fetch_alarm_history"}:
        return {**result, "total": 0, "alarms": [], "items": []}
    if "forecast" in tool_name:
        return {
            **result,
            "date": arguments.get("date", "2026-07-10"),
            "energy_type": "mock",
            "peak_kw": 512.0,
            "total_kwh": 3200.0,
            "series": [{"time": "2026-07-10 12:00:00", "forecast_kw": 512.0}],
        }
    return {
        **result,
        "date": arguments.get("date", "2026-07-10"),
        "value": 1.0,
        "unit": "kWh",
        "items": [{"site_id": site_id, "value": 1.0}],
    }


def _make_mock_tool(tool_name: str, case: EvalCase) -> Callable[..., dict[str, Any]]:
    """创建与产品 Tool 同名的确定性 mock 函数。"""
    def mock_tool(**arguments: Any) -> dict[str, Any]:
        return _mock_tool_result(tool_name, case, arguments)

    return mock_tool


@contextmanager
def _mock_tools_if_needed(config: EvalRunConfig, case: EvalCase):
    """Standard/测试模式声明 tools=mock 时，临时隔离产品真实 Tool 执行。"""
    if config.tools.kind != "mock":
        yield
        return

    from src.tools import TOOL_REGISTRY

    original_registry = TOOL_REGISTRY.copy()
    try:
        for tool_name in list(original_registry):
            TOOL_REGISTRY[tool_name] = _make_mock_tool(tool_name, case)
        yield
    finally:
        TOOL_REGISTRY.clear()
        TOOL_REGISTRY.update(original_registry)


def _infer_routing(
    tool_names: list[str], user_input: str = "", answer: str = "",
) -> tuple[list[str], Optional[str], Optional[str]]:
    """从实际 Tool calls 推导当前主图的 intent、Agent 与 Skill 标签。"""
    intents: list[str] = []
    has_navigation = False
    for name in tool_names:
        if name == "query_hvac_knowledge":
            intents.append("hvac")
        elif name == "navigate_to_page":
            has_navigation = True
        elif name == "export_data_table":
            intents.append("data_export")
        elif "forecast" in name:
            intents.append("forecast")
        elif "alarm" in name:
            intents.append("alarm_query")
        elif name.startswith("fetch_"):
            intents.append("monitor_query")
        elif name == "parse_business_intent":
            intents.append("energy_dispatch")
        elif name in {"search_memory", "search_relevant_memory", "save_memory"}:
            continue
    intents = list(dict.fromkeys(intents))
    if not intents and has_navigation:
        intents = ["navigation"]
    if "hvac" in intents:
        return intents, "hvac_expert", "hvac_expert"
    if any(intent in intents for intent in ("navigation", "data_export", "forecast", "alarm_query", "monitor_query")):
        return intents, "ui_router", "ui_router"
    if "energy_dispatch" in intents:
        return intents, "powerai", "energy_dispatch"
    if not intents:
        normalized = user_input.lower()
        if any(signal in normalized for signal in ("记得", "记忆", "偏好", "记住了什么")):
            intents = ["memory_operation"]
        elif "只能回答能源管理、暖通空调和平台操作相关问题" in answer:
            intents = ["out_of_domain"]
        elif _is_clarification_answer(answer):
            intents = ["clarification"]
        else:
            intents = ["general"]
    return intents, "main_graph", None


class GraphAdapter(BaseAdapter):
    """通过注入执行器适配编译后的 EnerGraph 图。"""

    adapter_name = "graph"


def create_energraph_executor(graph: Optional[Any] = None) -> Callable:
    """创建将真实 EnerGraph 状态映射到统一 AdapterResponse 的执行器。

    Args:
        graph: 可选的编译图或测试替身；为空时延迟加载项目全局图。

    Returns:
        可注入 GraphAdapter 的同步执行器。
    """
    def execute(case: EvalCase, config: EvalRunConfig, namespace: str) -> AdapterResponse:
        """执行单案例并提取回答、意图、Tool 调用与 token 证据。"""
        nonlocal graph
        _apply_eval_runtime_overrides(config)
        if graph is None:
            from src.graph.builder import graph as compiled_graph

            graph = compiled_graph
        from src.graph.builder import build_graph_config

        initial_state = {
            "user_input": case.input.user_message,
            "user_id": case.input.user_id,
            "site_id": case.input.site_id,
            "thread_id": namespace,
        }
        with _mock_tools_if_needed(config, case):
            state = graph.invoke(initial_state, config=build_graph_config(namespace))
        tool_calls = []
        input_tokens = 0
        output_tokens = 0
        saw_usage = False
        final_answer = state.get("final_report") or ""
        last_assistant_answer = ""
        for message in state.get("messages") or []:
            usage = getattr(message, "usage_metadata", None) or {}
            if usage:
                saw_usage = True
                input_tokens += int(usage.get("input_tokens") or 0)
                output_tokens += int(usage.get("output_tokens") or 0)
            for call in getattr(message, "tool_calls", None) or []:
                tool_calls.append(ToolCallRecord(
                    name=str(call.get("name", "unknown")),
                    arguments=call.get("args") or call.get("arguments") or {},
                ))
            content = _assistant_text(message)
            if content:
                last_assistant_answer = content
        if not final_answer:
            final_answer = last_assistant_answer
        inferred_intents, inferred_agent, inferred_skill = _infer_routing(
            [call.name for call in tool_calls],
            user_input=case.input.user_message,
            answer=final_answer,
        )
        return AdapterResponse(
            actual_intents=inferred_intents,
            actual_agent=inferred_agent,
            actual_skill=inferred_skill,
            tool_calls=tool_calls,
            answer=final_answer,
            input_tokens=input_tokens if saw_usage else None,
            output_tokens=output_tokens if saw_usage else None,
            error=state.get("error"),
            evidence_summary=(
                f"graph mode={config.mode}; namespace={namespace}; "
                f"messages={len(state.get('messages') or [])}"
            ),
        )

    return execute


def create_routing_fixture_executor() -> Callable:
    """创建读取 routing_output 的确定性 Fast 执行器。"""
    def execute(case: EvalCase, _config: EvalRunConfig, _namespace: str) -> AdapterResponse:
        output = case.fixtures.get("routing_output", {})
        return AdapterResponse(
            actual_intents=output.get("intents", []),
            actual_agent=output.get("agent"),
            actual_skill=output.get("skill"),
            observations={"routing": {"top_intents": output.get("top_intents", output.get("intents", []))}},
            evidence_summary=f"fixed routing fixture: {case.case_id}",
        )
    return execute
