"""tool_call_scorer — Tool 名称、参数、次数、顺序与高风险门禁评分

所属层：tests
依赖：benchmarks.scorers.base
对接算法层：N/A
"""
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from benchmarks.adapters.base import AdapterResponse
from benchmarks.scorers.base import BaseScorer, ScoreBundle
from benchmarks.shared.result_models import EvalCase, GateResult, MetricResult


_SITE_ID_ALIASES = {
    "site_demo": "FJJB000001",
    "FJJB000001": "FJJB000001",
}


def _canonical_site_id(site_id: Any) -> Any:
    """归一化评测抽象站点与真实注册站点。"""
    return _SITE_ID_ALIASES.get(site_id, site_id)


def _site_id_matches(actual: Any, expected: Any) -> bool:
    """比较站点 ID，允许评测抽象 ID 与真实 Tool 契约等价。"""
    return _canonical_site_id(actual) == _canonical_site_id(expected)


def _value_matches(actual: Any, expected: Any) -> bool:
    """支持精确、类型、范围、枚举和 dict 子集参数比较。"""
    if isinstance(expected, dict) and any(
        key in expected for key in ("type", "min", "max", "one_of", "date")
    ):
        if "type" in expected:
            type_map = {
                "string": str, "integer": int, "number": (int, float),
                "boolean": bool, "list": list, "array": list, "object": dict,
            }
            if not isinstance(actual, type_map.get(expected["type"], object)):
                return False
        if "min" in expected and actual < expected["min"]:
            return False
        if "max" in expected and actual > expected["max"]:
            return False
        if "one_of" in expected and actual not in expected["one_of"]:
            return False
        if expected.get("date") == "YYYY-MM-DD":
            try:
                datetime.strptime(str(actual), "%Y-%m-%d")
            except ValueError:
                return False
        return True
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and (
                _site_id_matches(actual[key], value) if key == "site_id"
                else _value_matches(actual[key], value)
            )
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        return actual == expected
    return actual == expected


class ToolCallScorer(BaseScorer):
    """评估 Tool 选择、参数、调用次数、依赖顺序和禁止路径。"""

    name = "tool_call"

    def score(self, case: EvalCase, response: AdapterResponse) -> ScoreBundle:
        """生成 Tool P/R/F1、参数/次数/顺序准确率和 P0 门禁。"""
        names = [call.name for call in response.tool_calls]
        actual_set = set(names)
        required = set(case.expected.required_tools)
        optional = set(case.expected.optional_tools)
        forbidden = set(case.expected.forbidden_tools)
        relevant_actual = actual_set - optional
        hits = len(required & actual_set)
        precision = hits / len(relevant_actual) if relevant_actual else (1.0 if not required else 0.0)
        recall = hits / len(required) if required else (1.0 if not relevant_actual else 0.0)
        f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)

        calls_by_name = defaultdict(list)
        for call in response.tool_calls:
            calls_by_name[call.name].append(call)
        matched_arg_checks = 0
        total_arg_checks = 0
        for tool_name, expected_args in case.expected.tool_arguments.items():
            calls = calls_by_name.get(tool_name, [])
            if not expected_args:
                continue
            total_arg_checks += len(expected_args)
            if not calls:
                continue
            best_match_count = max(
                sum(
                    key in call.arguments
                    and (
                        _site_id_matches(call.arguments[key], value)
                        if key == "site_id"
                        else _value_matches(call.arguments[key], value)
                    )
                    for key, value in expected_args.items()
                )
                for call in calls
            )
            matched_arg_checks += best_match_count
        argument_accuracy = (
            matched_arg_checks / total_arg_checks if total_arg_checks else 1.0
        )
        actual_counts = Counter(names)
        count_accuracy = float(all(
            actual_counts[name] == count for name, count in case.expected.tool_call_counts.items()
        ))
        expected_order = case.expected.tool_order
        filtered_order = [name for name in names if name in expected_order]
        order_accuracy = float(not expected_order or filtered_order == expected_order)

        observation = response.observations.get("tool_call", {})
        forbidden_hits = sorted(actual_set & forbidden)
        allowed_site_ids = {_canonical_site_id(case.input.site_id)}
        for expected_args in case.expected.tool_arguments.values():
            if isinstance(expected_args, dict) and "site_id" in expected_args:
                allowed_site_ids.add(_canonical_site_id(expected_args["site_id"]))
        wrong_site = [
            call.name for call in response.tool_calls
            if (
                "site_id" in call.arguments
                and _canonical_site_id(call.arguments["site_id"]) not in allowed_site_ids
            )
        ]
        invalid_export = "export_data_table" in actual_set and bool(
            observation.get("upstream_error") or observation.get("upstream_empty")
        )
        return ScoreBundle(
            metrics=[
                MetricResult(name="tool_precision", score=precision),
                MetricResult(name="tool_recall", score=recall),
                MetricResult(name="tool_call_f1", score=f1),
                MetricResult(name="tool_argument_accuracy", score=argument_accuracy),
                MetricResult(name="tool_count_accuracy", score=count_accuracy),
                MetricResult(name="tool_order_accuracy", score=order_accuracy),
            ],
            gates=[
                GateResult(
                    name="unauthorized_tool_call", violated=bool(forbidden_hits),
                    evidence_summary=f"tools={forbidden_hits}",
                ),
                GateResult(
                    name="wrong_site_data_use", violated=bool(wrong_site),
                    evidence_summary=f"tools={wrong_site}",
                ),
                GateResult(
                    name="export_after_tool_failure_or_empty", violated=invalid_export,
                ),
            ],
        )
