"""test_security_regression — T9 Security P0 离线回归门禁

所属层：tests
依赖：pytest, benchmarks.adapters.security_adapter, benchmarks.scorers.security_scorer
对接算法层：N/A
"""
from pathlib import Path

import pytest

from benchmarks.adapters import SecurityAdapter, create_security_fixture_executor
from benchmarks.datasets.security.v0_1 import load_security_cases
from benchmarks.scorers import SecurityScorer
from benchmarks.shared.config_models import load_run_config
from benchmarks.shared.result_models import EvalCase


ROOT = Path(__file__).resolve().parents[2]
CASES = [case for case in load_security_cases() if case.case_id.endswith("_v01")]
CONFIG = load_run_config(ROOT / "benchmarks/configs/fast.yaml")


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.case_id)
def test_security_p0_regression(case: EvalCase) -> None:
    """每个 Security 基础攻击面必须安全拒答且不触发 gate。"""
    response = SecurityAdapter(CONFIG, create_security_fixture_executor()).run(case)
    bundle = SecurityScorer().score(case, response)
    assert not any(gate.violated for gate in bundle.gates), case.case_id
    assert all(metric.score == 1.0 for metric in bundle.metrics), case.case_id
