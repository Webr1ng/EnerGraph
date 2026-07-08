"""tool_adapter — Tool 调用层的 Eval Adapter 边界

所属层：tests
依赖：benchmarks.adapters.base, benchmarks.shared
对接算法层：N/A
"""
from typing import Callable

from benchmarks.adapters.base import AdapterResponse, BaseAdapter
from benchmarks.shared.config_models import EvalRunConfig
from benchmarks.shared.result_models import EvalCase


class ToolAdapter(BaseAdapter):
    """适配固定 Mock 或真实 Tool 执行器。"""

    adapter_name = "tool"


def create_tool_fixture_executor() -> Callable:
    """创建读取 tool_output 的确定性 Fast 执行器。"""
    def execute(case: EvalCase, _config: EvalRunConfig, _namespace: str) -> AdapterResponse:
        output = case.fixtures.get("tool_output", {})
        return AdapterResponse(
            tool_calls=output.get("tool_calls", []),
            observations={"tool_call": {
                "upstream_error": output.get("upstream_error", False),
                "upstream_empty": output.get("upstream_empty", False),
            }},
            evidence_summary=f"fixed tool fixture: {case.case_id}",
        )
    return execute
