"""test_answer_benchmark — 验证 T11 多意图与最终回答质量 MiniBench

所属层：tests
依赖：pytest, benchmarks.adapters.answer_adapter, benchmarks.scorers.answer_scorer
对接算法层：N/A
"""
from pathlib import Path

import pytest

from benchmarks.adapters import AnswerAdapter, create_answer_fixture_executor
from benchmarks.adapters.base import AdapterResponse
from benchmarks.datasets.answer.v0_1 import load_answer_cases
from benchmarks.runners.run_all import exit_code_for_results, run_cases
from benchmarks.scorers import AnswerScorer, ScorerRegistry
from benchmarks.shared.config_models import load_run_config
from benchmarks.shared.report_generator import aggregate_results


ROOT = Path(__file__).resolve().parents[2]


def test_answer_dataset_has_30_multi_and_40_quality_records() -> None:
    """数据集应包含 30 条多意图和 40 条回答质量记录。"""
    cases = load_answer_cases()
    assert len(cases) == 70
    assert len([case for case in cases if "multi_intent" in case.tags]) == 30
    assert len([case for case in cases if "quality" in case.tags]) == 40


def test_answer_fast_suite_scores_all_metrics_at_one() -> None:
    """固定执行证据的 70-record Fast 集应完全通过。"""
    config = load_run_config(ROOT / "benchmarks/configs/fast.yaml")
    results = run_cases(
        load_answer_cases(), adapter=AnswerAdapter(config, create_answer_fixture_executor()),
        scorers=ScorerRegistry([AnswerScorer()]), run_id="answer-test",
        model_id="fixed-answer-v0.1", code_version="test", prompt_version="test",
    )
    summary = aggregate_results(results)
    assert exit_code_for_results(results) == 0
    assert summary["hard_gate_passed"] is True
    assert all(score == 1.0 for score in summary["metric_macro"].values())


@pytest.mark.parametrize(
    ("mutate", "gate_name"),
    [
        ({"executed_intents": ["cop"], "execution_order": ["cop"]}, "missing_intent_execution"),
        (
            {"executed_intents": ["cop", "energy"], "execution_order": ["energy", "cop"]},
            "dependency_order_violation",
        ),
    ],
)
def test_execution_drift_triggers_gate(mutate: dict, gate_name: str) -> None:
    """漏执行和依赖顺序错误必须触发独立 gate。"""
    case = next(case for case in load_answer_cases() if "multi_cop_energy" in case.case_id)
    response = AdapterResponse(
        answer="## 1. COP\n4.2\n## 2. 能耗\n128.5 kWh",
        observations={"answer_quality": mutate},
    )
    bundle = AnswerScorer().score(case, response)
    assert any(gate.name == gate_name and gate.violated for gate in bundle.gates)


def test_missing_section_and_forbidden_text_trigger_gates() -> None:
    """漏分段和过度跳转承诺必须触发回答 gate。"""
    case = next(case for case in load_answer_cases() if "multi_cop_energy" in case.case_id)
    response = AdapterResponse(
        answer="COP 4.2，能耗 128.5 kWh，已为您跳转。",
        observations={"answer_quality": {
            "executed_intents": ["cop", "energy"], "execution_order": ["cop", "energy"],
        }},
    )
    violated = {gate.name for gate in AnswerScorer().score(case, response).gates if gate.violated}
    assert {"missing_report_section", "forbidden_answer_behavior"}.issubset(violated)


def test_answer_scorer_accepts_controlled_failure_synonyms() -> None:
    """部分失败允许“查询失败”和“调用失败”两种受控同义表达。"""
    case = next(case for case in load_answer_cases() if "partial_failure" in case.case_id)
    response = AdapterResponse(
        answer=(
            "## 1. 能耗\n128.5 kWh。\n## 2. 报警\n"
            "报警接口调用失败。\n风险提示：结果不完整。"
        ),
        observations={"answer_quality": {
            "executed_intents": ["energy", "alarm"],
            "execution_order": ["energy", "alarm"],
        }},
    )

    quality = next(
        metric for metric in AnswerScorer().score(case, response).metrics
        if metric.name == "deterministic_answer_quality"
    )
    assert quality.score == 1.0


def test_answer_scorer_ignores_formatting_whitespace() -> None:
    """确定性文本检查不应把“3条”和“3 条”判为不同内容。"""
    case = next(case for case in load_answer_cases() if "alarm_export" in case.case_id)
    response = AdapterResponse(
        answer="## 1. 报警查询\n共3条。\n## 2. 数据导出\n格式为CSV。",
        observations={"answer_quality": {
            "executed_intents": ["alarm", "export"],
            "execution_order": ["alarm", "export"],
        }},
    )

    quality = next(
        metric for metric in AnswerScorer().score(case, response).metrics
        if metric.name == "deterministic_answer_quality"
    )
    assert quality.score == 1.0
