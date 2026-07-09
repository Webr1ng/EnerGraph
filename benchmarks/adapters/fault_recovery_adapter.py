"""fault_recovery_adapter — PostgreSQL 与外部依赖故障验收适配器

所属层：tests
依赖：benchmarks.adapters.base
对接算法层：N/A
"""
from typing import Callable

from benchmarks.adapters.base import AdapterResponse, BaseAdapter
from benchmarks.shared.config_models import EvalRunConfig
from benchmarks.shared.result_models import EvalCase


class FaultRecoveryAdapter(BaseAdapter):
    """适配故障恢复观测结果。"""

    adapter_name = "fault_recovery"


def create_fault_recovery_fixture_executor() -> Callable:
    """创建读取 fault_recovery_output 的确定性执行器。"""
    def execute(case: EvalCase, _config: EvalRunConfig, _namespace: str) -> AdapterResponse:
        output = case.fixtures.get("fault_recovery_output", {})
        return AdapterResponse(
            answer=str(output.get("evidence", "")),
            observations={"fault_recovery": output},
            evidence_summary=f"fixed fault recovery fixture: {case.case_id}",
        )

    return execute
