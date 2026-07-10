"""test_tool_call_benchmark — 验证 Tool Call MiniBench 80-record 集与门禁

所属层：tests
依赖：pytest, benchmarks.adapters, benchmarks.datasets.tool_call, benchmarks.scorers
对接算法层：N/A
"""
from pathlib import Path

import pytest

from benchmarks.adapters import ToolAdapter, create_tool_fixture_executor
from benchmarks.adapters.base import AdapterResponse
from benchmarks.datasets.tool_call.v0_1 import load_tool_call_cases
from benchmarks.runners.run_all import exit_code_for_results, run_cases
from benchmarks.scorers import ScorerRegistry, ToolCallScorer
from benchmarks.shared.config_models import load_run_config
from benchmarks.shared.report_generator import aggregate_results
from benchmarks.shared.result_models import ToolCallRecord


ROOT = Path(__file__).resolve().parents[2]


def test_tool_dataset_has_80_unique_records_and_high_risk_tags() -> None:
    """16 个基础场景应扩展为 80 条并覆盖导出、范围、错误和近邻。"""
    cases = load_tool_call_cases()
    assert len(cases) == 80
    assert len({case.case_id for case in cases}) == 80
    tags = {tag for case in cases for tag in case.tags}
    assert {"export", "range", "error", "negative", "near_neighbor"}.issubset(tags)


def test_tool_dataset_matches_real_site_and_navigation_contract() -> None:
    """Standard 集应使用已注册站点、真实 route 参数并容许查询后的导航。"""
    cases = load_tool_call_cases()
    energy = next(case for case in cases if "energy_summary" in case.case_id)
    navigation = next(case for case in cases if "navigation" in case.case_id)
    assert energy.input.site_id == "FJJB000001"
    assert energy.expected.tool_arguments["fetch_energy_summary"] == {
        "site_id": "FJJB000001",
    }
    assert "navigate_to_page" in energy.expected.optional_tools
    assert navigation.expected.tool_arguments["navigate_to_page"] == {
        "route": {"type": "string"},
    }


def test_tool_fast_suite_scores_all_metrics_at_one() -> None:
    """固定 Tool 响应的 80-record Fast 集应完全通过。"""
    config = load_run_config(ROOT / "benchmarks" / "configs" / "fast.yaml")
    cases = load_tool_call_cases()
    results = run_cases(
        cases,
        adapter=ToolAdapter(config, create_tool_fixture_executor()),
        scorers=ScorerRegistry([ToolCallScorer()]),
        run_id="tools-test", model_id="mock-tool-calling-v0.1",
        code_version="test", prompt_version="test",
    )
    summary = aggregate_results(results)
    assert exit_code_for_results(results) == 0
    assert len(results) == 80
    assert summary["hard_gate_passed"] is True
    assert all(score == 1.0 for score in summary["metric_macro"].values())


def test_argument_comparators_detect_wrong_type_range_and_date() -> None:
    """类型、范围和日期比较失败必须降低参数准确率。"""
    case = load_tool_call_cases()[0].model_copy(deep=True)
    case.expected.tool_arguments = {"demo": {
        "limit": {"type": "integer", "min": 1, "max": 10},
        "date": {"date": "YYYY-MM-DD"},
    }}
    response = AdapterResponse(tool_calls=[ToolCallRecord(
        name="demo", arguments={"limit": 99, "date": "2026/07/08"},
    )])
    metrics = {m.name: m.score for m in ToolCallScorer().score(case, response).metrics}
    assert metrics["tool_argument_accuracy"] == 0.0


def test_extra_legal_tool_arguments_and_repeated_calls_do_not_lower_accuracy() -> None:
    """模型补充合法细分参数、重复查询同一 Tool 时，期望子集命中即可。"""
    case = next(case for case in load_tool_call_cases() if "tool_cop_realtime_001" in case.case_id)
    response = AdapterResponse(tool_calls=[
        ToolCallRecord(
            name="fetch_efficiency_detail",
            arguments={"site_id": "FJJB000001", "param_name": "水系统平均COP"},
        ),
        ToolCallRecord(
            name="fetch_efficiency_detail",
            arguments={"site_id": "FJJB000001", "param_name": "水系统平均SCOP"},
        ),
    ])
    bundle = ToolCallScorer().score(case, response)
    metrics = {m.name: m.score for m in bundle.metrics}
    assert metrics["tool_argument_accuracy"] == 1.0
    assert not any(g.name == "wrong_site_data_use" and g.violated for g in bundle.gates)


def test_repeated_calls_must_match_expected_args_within_one_call() -> None:
    """同名 Tool 多次调用时，不能把不同调用的零散参数合成为满分。"""
    case = load_tool_call_cases()[0].model_copy(deep=True)
    case.expected.tool_arguments = {
        "fetch_energy_range": {
            "site_id": "FJJB000001",
            "start_date": "2026-07-01",
            "end_date": "2026-07-08",
        },
    }
    response = AdapterResponse(tool_calls=[
        ToolCallRecord(
            name="fetch_energy_range",
            arguments={"site_id": "FJJB000001", "start_date": "2026-07-01"},
        ),
        ToolCallRecord(
            name="fetch_energy_range",
            arguments={"site_id": "wrong_site", "end_date": "2026-07-08"},
        ),
    ])

    metrics = {m.name: m.score for m in ToolCallScorer().score(case, response).metrics}

    assert metrics["tool_argument_accuracy"] == pytest.approx(2 / 3)


def test_site_demo_and_registered_site_id_are_gate_equivalent() -> None:
    """旧评测抽象站点与当前真实注册站点等价，不应误触发 wrong_site gate。"""
    case = load_tool_call_cases()[0].model_copy(deep=True)
    case.input.site_id = "site_demo"
    case.expected.tool_arguments = {
        "fetch_energy_summary": {"site_id": "site_demo"},
    }
    response = AdapterResponse(tool_calls=[ToolCallRecord(
        name="fetch_energy_summary",
        arguments={"site_id": "FJJB000001", "date": "2026-07-09"},
    )])
    bundle = ToolCallScorer().score(case, response)
    metrics = {m.name: m.score for m in bundle.metrics}
    assert metrics["tool_argument_accuracy"] == 1.0
    assert not any(g.name == "wrong_site_data_use" and g.violated for g in bundle.gates)


@pytest.mark.parametrize(
    ("response", "gate_name"),
    [
        (
            AdapterResponse(tool_calls=[ToolCallRecord(name="export_data_table", arguments={})]),
            "unauthorized_tool_call",
        ),
        (
            AdapterResponse(tool_calls=[ToolCallRecord(
                name="fetch_energy_summary", arguments={"site_id": "wrong_site"},
            )]),
            "wrong_site_data_use",
        ),
        (
            AdapterResponse(
                tool_calls=[ToolCallRecord(name="export_data_table", arguments={})],
                observations={"tool_call": {"upstream_empty": True}},
            ),
            "export_after_tool_failure_or_empty",
        ),
    ],
)
def test_tool_negative_paths_trigger_hard_gates(
    response: AdapterResponse, gate_name: str,
) -> None:
    """越权、错误站点和无数据假导出必须触发硬门禁。"""
    case = next(case for case in load_tool_call_cases() if "empty" in case.case_id)
    bundle = ToolCallScorer().score(case, response)
    assert any(gate.name == gate_name and gate.violated for gate in bundle.gates)


def test_tool_order_and_count_drift_are_scored_separately() -> None:
    """工具顺序与调用次数漂移应独立定位。"""
    case = next(case for case in load_tool_call_cases() if "energy_export" in case.case_id)
    case.expected.tool_call_counts = {"fetch_energy_range": 1}
    response = AdapterResponse(tool_calls=[
        ToolCallRecord(name="export_data_table", arguments={}),
        ToolCallRecord(name="fetch_energy_range", arguments={"site_id": "site_demo"}),
        ToolCallRecord(name="fetch_energy_range", arguments={"site_id": "site_demo"}),
    ])
    metrics = {m.name: m.score for m in ToolCallScorer().score(case, response).metrics}
    assert metrics["tool_order_accuracy"] == 0.0
    assert metrics["tool_count_accuracy"] == 0.0
