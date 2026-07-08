"""graph_adapter — LangGraph 入口的 Eval Adapter 边界

所属层：tests
依赖：benchmarks.adapters.base, src.graph.builder
对接算法层：N/A
"""
from typing import Any, Callable, Optional

from benchmarks.adapters.base import AdapterResponse, BaseAdapter
from benchmarks.shared.config_models import EvalRunConfig
from benchmarks.shared.result_models import EvalCase, ToolCallRecord


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
        elif any(signal in answer for signal in (
            "请明确", "请具体", "请问您", "请提供", "请告诉我", "您想查看哪方面", "请选择",
        )):
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
    if graph is None:
        from src.graph.builder import graph as compiled_graph

        graph = compiled_graph

    def execute(case: EvalCase, config: EvalRunConfig, namespace: str) -> AdapterResponse:
        """执行单案例并提取回答、意图、Tool 调用与 token 证据。"""
        from src.graph.builder import build_graph_config

        initial_state = {
            "user_input": case.input.user_message,
            "user_id": case.input.user_id,
            "site_id": case.input.site_id,
            "thread_id": namespace,
        }
        state = graph.invoke(initial_state, config=build_graph_config(namespace))
        tool_calls = []
        input_tokens = 0
        output_tokens = 0
        saw_usage = False
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
        inferred_intents, inferred_agent, inferred_skill = _infer_routing(
            [call.name for call in tool_calls],
            user_input=case.input.user_message,
            answer=state.get("final_report") or "",
        )
        return AdapterResponse(
            actual_intents=inferred_intents,
            actual_agent=inferred_agent,
            actual_skill=inferred_skill,
            tool_calls=tool_calls,
            answer=state.get("final_report") or "",
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
