"""test_routing_regression — T9 Routing P0 离线回归门禁

所属层：tests
依赖：pytest, benchmarks.adapters.graph_adapter, benchmarks.scorers.routing_scorer
对接算法层：N/A
"""
from pathlib import Path

import pytest

from benchmarks.adapters import GraphAdapter, create_routing_fixture_executor
from benchmarks.datasets.routing.v0_1 import load_routing_cases
from benchmarks.scorers import RoutingScorer
from benchmarks.shared.config_models import load_run_config
from benchmarks.shared.result_models import EvalCase


ROOT = Path(__file__).resolve().parents[2]
CASES = [case for case in load_routing_cases() if case.case_id.endswith("_v01")]
CONFIG = load_run_config(ROOT / "benchmarks/configs/fast.yaml")


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.case_id)
def test_routing_p0_regression(case: EvalCase) -> None:
    """每个 Routing 基础意图必须保持路由指标全一。"""
    response = GraphAdapter(CONFIG, create_routing_fixture_executor()).run(case)
    bundle = RoutingScorer().score(case, response)
    assert not any(gate.violated for gate in bundle.gates), case.case_id
    assert all(metric.score == 1.0 for metric in bundle.metrics), case.case_id
