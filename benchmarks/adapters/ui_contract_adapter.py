"""ui_contract_adapter — SSE、UIAction 与 DataCard 固定契约适配器

所属层：tests
依赖：benchmarks.adapters.base
对接算法层：N/A
"""
from typing import Callable

from benchmarks.adapters.base import AdapterResponse, BaseAdapter
from benchmarks.shared.config_models import EvalRunConfig
from benchmarks.shared.result_models import EvalCase


class UIContractAdapter(BaseAdapter):
    """适配固定 SSE 事件流及前端消费观测。"""

    adapter_name = "ui_contract"


def create_ui_contract_fixture_executor() -> Callable:
    """创建读取 ui_contract_output 的确定性执行器。"""
    def execute(case: EvalCase, _config: EvalRunConfig, _namespace: str) -> AdapterResponse:
        output = case.fixtures.get("ui_contract_output", {})
        events = output.get("events", [])
        answer = "".join(
            event.get("data", {}).get("text", "")
            for event in events if event.get("event") == "text"
        )
        return AdapterResponse(
            answer=answer,
            protocol_events=events,
            observations={"ui_contract": output.get("observations", {})},
            evidence_summary=f"fixed UI contract fixture: {case.case_id}",
        )

    return execute
