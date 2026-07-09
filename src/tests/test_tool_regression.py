"""test_tool_regression — T9 Tool Call P0 离线回归门禁

所属层：tests
依赖：pytest, benchmarks.adapters.tool_adapter, benchmarks.scorers.tool_call_scorer
对接算法层：N/A
"""
from pathlib import Path

import pytest

from benchmarks.adapters import ToolAdapter, create_tool_fixture_executor
from benchmarks.datasets.tool_call.v0_1 import load_tool_call_cases
from benchmarks.scorers import ToolCallScorer
from benchmarks.shared.config_models import load_run_config
from benchmarks.shared.result_models import EvalCase


ROOT = Path(__file__).resolve().parents[2]
CASES = [case for case in load_tool_call_cases() if case.case_id.endswith("_v01")]
CONFIG = load_run_config(ROOT / "benchmarks/configs/fast.yaml")


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.case_id)
def test_tool_p0_regression(case: EvalCase) -> None:
    """每个 Tool 基础场景必须保持选择、参数、次数和顺序正确。"""
    response = ToolAdapter(CONFIG, create_tool_fixture_executor()).run(case)
    bundle = ToolCallScorer().score(case, response)
    assert not any(gate.violated for gate in bundle.gates), case.case_id
    assert all(metric.score == 1.0 for metric in bundle.metrics), case.case_id
