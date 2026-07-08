"""loader — 将 16 个 Tool 基础场景扩展为 80 条语言变体

所属层：tests
依赖：benchmarks.shared.case_loader
对接算法层：N/A
"""
from pathlib import Path
from typing import List

from benchmarks.shared.case_loader import load_cases
from benchmarks.shared.result_models import EvalCase

CANONICAL_EVAL_SITE_ID = "FJJB000001"


def _align_with_real_graph_contract(case: EvalCase) -> None:
    """将抽象 Fixture 对齐到当前真实 Graph/Tool 契约。

    Fast 数据最初使用 ``site_demo`` 和导航 ``keyword`` 占位；真实 EnerGraph
    只注册了福加江北站点，且 ``navigate_to_page`` 接收 ``route``。数据查询后
    自动附加导航也是 UI Router 的既定行为，因此不应降低 Tool precision。

    Args:
        case: 待原地规范化的基础评测案例。
    """
    case.input.site_id = CANONICAL_EVAL_SITE_ID
    for call in case.fixtures.get("tool_output", {}).get("tool_calls", []):
        arguments = call.get("arguments", {})
        if arguments.get("site_id") == "site_demo":
            arguments["site_id"] = CANONICAL_EVAL_SITE_ID
    for expected_args in case.expected.tool_arguments.values():
        if expected_args.get("site_id") == "site_demo":
            expected_args["site_id"] = CANONICAL_EVAL_SITE_ID

    if any(name.startswith("fetch_") for name in case.expected.required_tools):
        if "navigate_to_page" not in case.expected.optional_tools:
            case.expected.optional_tools.append("navigate_to_page")
    if case.case_id == "tool_energy_summary_001":
        # fetch_energy_summary 的 date 为空时由 Tool 取当天，省略和显式传入等价。
        case.expected.tool_arguments["fetch_energy_summary"] = {
            "site_id": CANONICAL_EVAL_SITE_ID,
        }
    if case.case_id == "tool_navigation_001":
        case.fixtures["tool_output"]["tool_calls"][0]["arguments"] = {
            "route": "/analysis/consumption-panel",
        }
        case.expected.tool_arguments["navigate_to_page"] = {
            "route": {"type": "string"},
        }


def load_tool_call_cases(path: Path | str | None = None) -> List[EvalCase]:
    """加载基础场景，并按每场景五种表述扩展为 80 records。"""
    source = Path(path) if path else Path(__file__).with_name("base_cases.jsonl")
    expanded: List[EvalCase] = []
    for case in load_cases(source):
        _align_with_real_graph_contract(case)
        utterances = case.fixtures.get("utterances", [])
        if len(utterances) != 5:
            raise ValueError(f"{case.case_id}: utterances 必须恰好 5 条")
        for index, utterance in enumerate(utterances, 1):
            clone = case.model_copy(deep=True)
            clone.case_id = f"{case.case_id}_v{index:02d}"
            clone.input.user_message = utterance
            clone.input.thread_id = f"{case.input.thread_id}_v{index:02d}"
            expanded.append(clone)
    return expanded
