"""test_ui_contract_benchmark — 验证 T12 前端契约 MiniBench

所属层：tests
依赖：pytest, benchmarks.adapters.ui_contract_adapter, benchmarks.scorers.ui_contract_scorer
对接算法层：N/A
"""
from copy import deepcopy
from pathlib import Path

import pytest

from benchmarks.adapters import UIContractAdapter, create_ui_contract_fixture_executor
from benchmarks.adapters.base import AdapterResponse
from benchmarks.datasets.ui_contract.v0_1 import load_ui_contract_cases
from benchmarks.runners.run_all import exit_code_for_results, run_cases
from benchmarks.scorers import ScorerRegistry, UIContractScorer
from benchmarks.shared.config_models import load_run_config
from benchmarks.shared.report_generator import aggregate_results


ROOT = Path(__file__).resolve().parents[2]


def test_ui_contract_dataset_has_30_records_and_required_tags() -> None:
    """数据集应为 30 条并覆盖计划要求的异常场景。"""
    cases = load_ui_contract_cases()
    tags = {tag for case in cases for tag in case.tags}
    assert len(cases) == 30
    assert {"all_events", "restricted", "empty_card", "chart_failure", "error", "interrupted"}.issubset(tags)


def test_ui_contract_fast_suite_scores_all_metrics_at_one() -> None:
    """固定 30-record 契约集应全部通过。"""
    config = load_run_config(ROOT / "benchmarks/configs/fast.yaml")
    results = run_cases(
        load_ui_contract_cases(),
        adapter=UIContractAdapter(config, create_ui_contract_fixture_executor()),
        scorers=ScorerRegistry([UIContractScorer()]), run_id="ui-contract-test",
        model_id="fixed-ui-contract-v0.1", code_version="test", prompt_version="test",
    )
    summary = aggregate_results(results)
    assert exit_code_for_results(results) == 0
    assert summary["hard_gate_passed"] is True
    assert all(score == 1.0 for score in summary["metric_macro"].values())


@pytest.mark.parametrize(
    ("mutator", "gate_name"),
    [
        (lambda events: events[:-1], "invalid_terminal_event"),
        (lambda events: events + [{"event": "done", "data": {}}], "invalid_terminal_event"),
        (lambda events: [{"event": "tool_result", "data": {"name": "x", "result": {}}}] + events, "invalid_sse_order"),
        (lambda events: [{"event": "text", "data": {}}] + events, "invalid_sse_schema"),
    ],
)
def test_protocol_drift_triggers_independent_gates(mutator, gate_name: str) -> None:
    """断流、重复终态、乱序和缺字段必须触发独立 gate。"""
    case = next(case for case in load_ui_contract_cases() if "direct_text" in case.case_id)
    events = deepcopy(case.fixtures["ui_contract_output"]["events"])
    bundle = UIContractScorer().score(case, AdapterResponse(protocol_events=mutator(events)))
    assert any(gate.name == gate_name and gate.violated for gate in bundle.gates)


def test_restricted_duplicate_and_unnamed_actions_are_rejected() -> None:
    """受限、重复或缺少注册名称的路由动作必须拒绝。"""
    case = load_ui_contract_cases()[0]
    bad = {"event": "action", "data": {"type": "navigate", "route": "/cockpit", "name": "", "params": {}, "meta": {}}}
    response = AdapterResponse(protocol_events=[bad, bad, {"event": "done", "data": {}}])
    bundle = UIContractScorer().score(case, response)
    assert any(gate.name == "invalid_ui_action" and gate.violated for gate in bundle.gates)


def test_datacard_row_drift_and_forged_link_are_rejected() -> None:
    """DataCard rows 漂移和正文伪造下载链接必须分别触发 gate。"""
    case = next(case for case in load_ui_contract_cases() if "datacard" in case.case_id)
    events = deepcopy(case.fixtures["ui_contract_output"]["events"])
    events[0]["data"]["text"] = "请点击[下载](/export/fake)。"
    response = AdapterResponse(
        protocol_events=events,
        observations={"ui_contract": {
            "source_rows": [{"date": "2026-07-08"}],
            "chart_rows": [{"date": "2026-07-09"}],
            "csv_rows": [{"date": "2026-07-08"}],
        }},
    )
    violated = {gate.name for gate in UIContractScorer().score(case, response).gates if gate.violated}
    assert {"datacard_rows_mismatch", "forged_body_link_or_duplicate_text"}.issubset(violated)
