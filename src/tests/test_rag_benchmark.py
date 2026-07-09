"""test_rag_benchmark — 验证 T10 HVAC RAG MiniBench 指标与门禁

所属层：tests
依赖：pytest, benchmarks.adapters.rag_adapter, benchmarks.scorers.rag_scorer
对接算法层：N/A
"""
from pathlib import Path

import pytest

from benchmarks.adapters import RagAdapter, create_rag_fixture_executor
from benchmarks.adapters.base import AdapterResponse
from benchmarks.datasets.rag.v0_1 import load_rag_cases
from benchmarks.runners.run_all import exit_code_for_results, run_cases
from benchmarks.scorers import RagScorer, ScorerRegistry
from benchmarks.shared.config_models import load_run_config
from benchmarks.shared.report_generator import aggregate_results


ROOT = Path(__file__).resolve().parents[2]


def test_rag_dataset_has_50_unique_records_and_answerability() -> None:
    """10 个基础场景应扩展为 50 条并覆盖可回答、拒答和近邻。"""
    cases = load_rag_cases()
    assert len(cases) == 50
    assert len({case.case_id for case in cases}) == 50
    tags = {tag for case in cases for tag in case.tags}
    assert {"answerable", "unanswerable", "low_confidence", "near_neighbor"}.issubset(tags)


def test_rag_fast_suite_scores_all_metrics_at_one() -> None:
    """固定语料的 50-record Fast 集应完全通过。"""
    config = load_run_config(ROOT / "benchmarks/configs/fast.yaml")
    results = run_cases(
        load_rag_cases(), adapter=RagAdapter(config, create_rag_fixture_executor()),
        scorers=ScorerRegistry([RagScorer()]), run_id="rag-test",
        model_id="fixed-rag-v0.1", code_version="test", prompt_version="test",
    )
    summary = aggregate_results(results)
    assert exit_code_for_results(results) == 0
    assert summary["hard_gate_passed"] is True
    assert all(score == 1.0 for score in summary["metric_macro"].values())


@pytest.mark.parametrize(
    ("case_fragment", "response", "gate_name"),
    [
        (
            "unanswerable_quantum",
            AdapterResponse(answer="量子空调可以提升效率。", observations={"rag": {}}),
            "answered_low_confidence",
        ),
        (
            "unanswerable_quantum",
            AdapterResponse(answer="知识库依据不足，无法回答。", observations={"rag": {
                "low_confidence": False,
            }}),
            "missed_low_confidence",
        ),
        (
            "delta_t",
            AdapterResponse(answer="无依据回答", observations={"rag": {"unsupported_claims": True}}),
            "unsupported_rag_answer",
        ),
        (
            "delta_t",
            AdapterResponse(answer="回答", observations={"rag": {
                "citations": ["hvac_6", "hvac_106", "hvac_206", "hvac_306"],
            }}),
            "too_many_or_invalid_citations",
        ),
        (
            "delta_t",
            AdapterResponse(answer="回答", observations={"rag": {"index_missing": True}}),
            "rag_index_unavailable",
        ),
    ],
)
def test_rag_negative_paths_trigger_gates(
    case_fragment: str, response: AdapterResponse, gate_name: str,
) -> None:
    """低置信度补答、无依据回答、错误引用和索引缺失必须触发 gate。"""
    case = next(case for case in load_rag_cases() if case_fragment in case.case_id)
    bundle = RagScorer().score(case, response)
    assert any(gate.name == gate_name and gate.violated for gate in bundle.gates)
