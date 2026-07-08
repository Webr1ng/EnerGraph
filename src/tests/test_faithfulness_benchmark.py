"""test_faithfulness_benchmark — 验证 T7 数据忠实度 MiniBench 与硬门禁

所属层：tests
依赖：pytest, benchmarks.adapters, benchmarks.datasets.faithfulness, benchmarks.scorers
对接算法层：N/A
"""
from pathlib import Path

import pytest

from benchmarks.adapters import FaithfulnessAdapter, create_faithfulness_fixture_executor
from benchmarks.adapters.base import AdapterResponse
from benchmarks.datasets.faithfulness.v0_1 import load_faithfulness_cases
from benchmarks.runners.run_all import exit_code_for_results, run_cases
from benchmarks.scorers import FaithfulnessScorer, ScorerRegistry
from benchmarks.shared.config_models import load_run_config
from benchmarks.shared.report_generator import aggregate_results


ROOT = Path(__file__).resolve().parents[2]


def test_faithfulness_dataset_has_50_unique_records_and_risk_tags() -> None:
    """10 个基础场景应扩展为 50 条并覆盖 P0 风险类型。"""
    cases = load_faithfulness_cases()
    assert len(cases) == 50
    assert len({case.case_id for case in cases}) == 50
    tags = {tag for case in cases for tag in case.tags}
    assert {"numeric", "partial", "empty", "error", "conflict", "stale", "data_card"}.issubset(tags)


def test_faithfulness_fast_suite_scores_all_metrics_at_one() -> None:
    """固定证据的 50-record Fast 集应完全通过。"""
    config = load_run_config(ROOT / "benchmarks/configs/fast.yaml")
    results = run_cases(
        load_faithfulness_cases(),
        adapter=FaithfulnessAdapter(config, create_faithfulness_fixture_executor()),
        scorers=ScorerRegistry([FaithfulnessScorer()]),
        run_id="faith-test", model_id="fixed-evidence-v0.1",
        code_version="test", prompt_version="test",
    )
    summary = aggregate_results(results)
    assert exit_code_for_results(results) == 0
    assert summary["hard_gate_passed"] is True
    assert all(score == 1.0 for score in summary["metric_macro"].values())


@pytest.mark.parametrize(
    ("mutate", "gate_name"),
    [
        ({"answer": "今日能耗为 999 kWh。"}, "unsupported_energy_numeric"),
        ({"answer": "今日能耗为 128.5 MWh。"}, "wrong_unit_or_site"),
        ({"answer": "今日能耗为 128.5 kWh，其他站点为 5 kWh。"}, "wrong_unit_or_site"),
    ],
)
def test_numeric_and_site_drift_trigger_hard_gates(mutate: dict, gate_name: str) -> None:
    """无依据数值、错误单位和错误站点必须触发硬门禁。"""
    case = next(case for case in load_faithfulness_cases() if "energy_exact" in case.case_id)
    case.fixtures["faithfulness_expected"]["forbidden_sites"] = ["其他站点"]
    bundle = FaithfulnessScorer().score(case, AdapterResponse(**mutate))
    assert any(gate.name == gate_name and gate.violated for gate in bundle.gates)


def test_missing_abstention_triggers_gate() -> None:
    """空数据仍编造数值必须同时命中数值和拒答门禁。"""
    case = next(case for case in load_faithfulness_cases() if "empty_abstain" in case.case_id)
    bundle = FaithfulnessScorer().score(case, AdapterResponse(answer="今日能耗为 88 kWh。"))
    violated = {gate.name for gate in bundle.gates if gate.violated}
    assert {"unsupported_energy_numeric", "missing_required_abstention"}.issubset(violated)


def test_fabricated_data_card_triggers_gate() -> None:
    """DataCard rows 与证据不一致必须触发硬门禁。"""
    case = next(case for case in load_faithfulness_cases() if "datacard" in case.case_id)
    response = AdapterResponse(
        answer="表格包含 100 kWh 和 120 kWh。",
        observations={"faithfulness": {"data_card": {"title": "两日能耗", "rows": []}}},
    )
    bundle = FaithfulnessScorer().score(case, response)
    assert any(gate.name == "fabricated_data_card" and gate.violated for gate in bundle.gates)
