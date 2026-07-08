"""test_routing_benchmark — 验证 Routing MiniBench 80-record 数据集与评分

所属层：tests
依赖：pytest, benchmarks.adapters, benchmarks.datasets.routing, benchmarks.scorers
对接算法层：N/A
"""
from pathlib import Path

from benchmarks.adapters import GraphAdapter, create_routing_fixture_executor
from benchmarks.adapters.graph_adapter import _infer_routing
from benchmarks.adapters.base import AdapterResponse
from benchmarks.datasets.routing.v0_1 import load_routing_cases
from benchmarks.runners.run_all import exit_code_for_results, run_cases
from benchmarks.scorers import RoutingScorer, ScorerRegistry
from benchmarks.shared.config_models import load_run_config
from benchmarks.shared.report_generator import aggregate_results


ROOT = Path(__file__).resolve().parents[2]


def test_routing_dataset_has_80_unique_records_and_required_domains() -> None:
    """16 个基础场景应扩展为 80 条并覆盖关键业务路由。"""
    cases = load_routing_cases()
    assert len(cases) == 80
    assert len({case.case_id for case in cases}) == 80
    expected_intents = {intent for case in cases for intent in case.expected.intents}
    assert {
        "hvac", "monitor_query", "alarm_query", "navigation", "data_export",
        "forecast", "energy_dispatch", "memory_operation", "general",
        "out_of_domain", "clarification",
    }.issubset(expected_intents)


def test_routing_fast_suite_scores_all_metrics_at_one() -> None:
    """固定路由响应的 80-record Fast 集应完全通过。"""
    config = load_run_config(ROOT / "benchmarks" / "configs" / "fast.yaml")
    cases = load_routing_cases()
    results = run_cases(
        cases,
        adapter=GraphAdapter(config, create_routing_fixture_executor()),
        scorers=ScorerRegistry([RoutingScorer()]),
        run_id="routing-test", model_id="mock-routing-v0.1",
        code_version="test", prompt_version="test",
    )
    summary = aggregate_results(results)
    assert exit_code_for_results(results) == 0
    assert len(results) == 80
    assert all(score == 1.0 for score in summary["metric_macro"].values())


def test_routing_scorer_detects_intent_agent_and_skill_drift() -> None:
    """模型路由漂移必须分别反映在 intent、Agent、Skill 指标。"""
    case = next(case for case in load_routing_cases() if "hvac" in case.tags)
    response = AdapterResponse(
        actual_intents=["monitor_query"], actual_agent="ui_router", actual_skill="ui_router",
        observations={"routing": {"top_intents": ["monitor_query", "hvac"]}},
    )
    scores = {metric.name: metric.score for metric in RoutingScorer().score(case, response).metrics}
    assert scores["intent_accuracy"] == 0.0
    assert scores["intent_macro_f1"] == 0.0
    assert scores["intent_top3_accuracy"] == 1.0
    assert scores["agent_routing_accuracy"] == 0.0
    assert scores["skill_routing_accuracy"] == 0.0


def test_routing_variants_preserve_expected_label() -> None:
    """同一基础场景的五种改写必须共享稳定期望标签。"""
    cases = [case for case in load_routing_cases() if case.case_id.startswith("routing_hvac_fault_001")]
    assert len(cases) == 5
    assert {tuple(case.expected.intents) for case in cases} == {("hvac",)}
    assert len({case.input.user_message for case in cases}) == 5


def test_no_tool_routes_infer_memory_rejection_and_clarification() -> None:
    """无 Tool 回答也应区分记忆、域外拒答和澄清，不都压成 general。"""
    assert _infer_routing([], "你记得我的偏好吗", "") == (
        ["memory_operation"], "main_graph", None
    )
    assert _infer_routing([], "写一首诗", "抱歉，我只能回答能源管理、暖通空调和平台操作相关问题") == (
        ["out_of_domain"], "main_graph", None
    )
    assert _infer_routing([], "帮我看看", "请明确您想查看的数据类型") == (
        ["clarification"], "main_graph", None
    )


def test_auxiliary_navigation_and_memory_tools_do_not_create_extra_intents() -> None:
    """查询后的导航与澄清前的记忆检索属于辅助调用，不是额外用户意图。"""
    assert _infer_routing(["fetch_pv_forecast", "navigate_to_page"], "查询光伏预测", "") == (
        ["forecast"], "ui_router", "ui_router"
    )
    assert _infer_routing(
        ["search_relevant_memory"], "帮我看看数据", "请告诉我站点 ID 和数据类型"
    ) == (["clarification"], "main_graph", None)
    assert _infer_routing([], "帮我看看数据", "您想查看哪方面的数据？请选择") == (
        ["clarification"], "main_graph", None
    )
    assert _infer_routing(["navigate_to_page"], "打开能耗分析页面", "") == (
        ["navigation"], "ui_router", "ui_router"
    )


def test_routing_standard_config_accepts_loaded_local_env() -> None:
    """项目 settings 加载后，Standard 配置应识别 .env 中的本地模型变量。"""
    from src.config.settings import settings as loaded_settings

    assert loaded_settings.model.provider
    config = load_run_config(ROOT / "benchmarks" / "configs" / "routing_standard.yaml")
    assert config.mode == "standard"
    assert config.llm.kind == "real"
