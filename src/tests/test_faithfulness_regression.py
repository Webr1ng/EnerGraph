"""test_faithfulness_regression — T9 Faithfulness P0 离线回归门禁

所属层：tests
依赖：pytest, benchmarks.adapters.faithfulness_adapter, benchmarks.scorers.faithfulness_scorer
对接算法层：N/A
"""
from pathlib import Path

import pytest

from benchmarks.adapters import FaithfulnessAdapter, create_faithfulness_fixture_executor
from benchmarks.datasets.faithfulness.v0_1 import load_faithfulness_cases
from benchmarks.scorers import FaithfulnessScorer
from benchmarks.shared.config_models import load_run_config
from benchmarks.shared.result_models import EvalCase


ROOT = Path(__file__).resolve().parents[2]
CASES = [case for case in load_faithfulness_cases() if case.case_id.endswith("_v01")]
CONFIG = load_run_config(ROOT / "benchmarks/configs/fast.yaml")


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.case_id)
def test_faithfulness_p0_regression(case: EvalCase) -> None:
    """每个 Faithfulness 基础证据场景必须保持指标全一且 gate 为零。"""
    response = FaithfulnessAdapter(CONFIG, create_faithfulness_fixture_executor()).run(case)
    bundle = FaithfulnessScorer().score(case, response)
    assert not any(gate.violated for gate in bundle.gates), case.case_id
    assert all(metric.score == 1.0 for metric in bundle.metrics), case.case_id
