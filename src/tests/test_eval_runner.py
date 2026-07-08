"""test_eval_runner — 验证 T3 Runner、Scorer、报告、续跑和 baseline diff

所属层：tests
依赖：pytest, benchmarks.runners, benchmarks.scorers, benchmarks.shared
对接算法层：N/A
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from benchmarks.adapters import GraphAdapter
from benchmarks.adapters.base import AdapterResponse
from benchmarks.fixtures import FixtureRepository
from benchmarks.runners.run_all import (
    exit_code_for_results,
    load_completed_results,
    run_cases,
    select_cases,
)
from benchmarks.scorers import ExpectedBehaviorScorer, ScorerRegistry
from benchmarks.shared.case_loader import load_cases
from benchmarks.shared.config_models import load_run_config
from benchmarks.shared.report_generator import aggregate_results, compare_baseline, write_report
from benchmarks.shared.result_models import EvalCase
from benchmarks.shared.run_metadata import build_run_manifest


ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "benchmarks" / "configs" / "fast.yaml"
FIXTURES = ROOT / "benchmarks" / "fixtures" / "scripted_responses.json"
EXAMPLE = ROOT / "benchmarks" / "datasets" / "_examples" / "minimal_valid.jsonl"


def _run(cases: list[EvalCase], adapter: GraphAdapter):
    """以固定元数据运行测试案例。"""
    return run_cases(
        cases,
        adapter=adapter,
        scorers=ScorerRegistry([ExpectedBehaviorScorer()]),
        run_id="run-test",
        model_id="mock-scripted-v0.1",
        code_version="abc123",
        prompt_version="git:abc123",
    )


def test_fast_case_generates_passing_summary_and_reports(tmp_path: Path) -> None:
    """最小 Fast 案例应生成三类报告且硬门禁通过。"""
    config = load_run_config(CONFIG)
    cases = load_cases(EXAMPLE)
    adapter = GraphAdapter(config, FixtureRepository.from_json(FIXTURES).execute)
    results = _run(cases, adapter)
    manifest = build_run_manifest(
        run_id="run-test",
        config=config,
        dataset_versions={"routing": "0.1"},
        model_id="mock-scripted-v0.1",
        project_root=ROOT,
        started_at=datetime(2026, 7, 7, tzinfo=timezone.utc),
    )
    manifest.finished_at = datetime(2026, 7, 7, 0, 1, tzinfo=timezone.utc)

    payload = write_report(tmp_path, results, manifest, baseline={"failed_cases": []})

    assert exit_code_for_results(results) == 0
    assert payload["summary"]["hard_gate_passed"] is True
    assert payload["summary"]["overall_macro"] == 1.0
    assert payload["summary"]["overall_micro"] == 1.0
    assert {path.name for path in tmp_path.iterdir()} == {
        "results.json", "run_manifest.json", "summary.md"
    }
    assert "mock-scripted-v0.1" in (tmp_path / "summary.md").read_text(encoding="utf-8")


def test_hard_gate_failure_returns_nonzero_exit() -> None:
    """回答命中禁止文本时应触发硬门禁并返回非零退出码。"""
    case = load_cases(EXAMPLE)[0].model_copy(deep=True)
    case.expected.answer_forbidden = ["青山大模型"]
    config = load_run_config(CONFIG)
    adapter = GraphAdapter(config, FixtureRepository.from_json(FIXTURES).execute)
    results = _run([case], adapter)

    assert exit_code_for_results(results) == 1
    assert any(gate.name == "forbidden_answer_text" and gate.violated for gate in results[0].gates)


def test_failure_isolated_and_later_case_still_runs() -> None:
    """单案例 Adapter 异常不得阻断后续案例。"""
    first = load_cases(EXAMPLE)[0]
    second = first.model_copy(deep=True)
    second.case_id = "routing_greeting_002"
    calls: list[str] = []

    def executor(case, *_args):
        calls.append(case.case_id)
        if case.case_id == first.case_id:
            raise RuntimeError("broken fixture")
        return AdapterResponse(answer="青山大模型")

    results = _run([first, second], GraphAdapter(load_run_config(CONFIG), executor))

    assert calls == [first.case_id, second.case_id]
    assert results[0].error and "broken fixture" in results[0].error
    assert results[1].error is None


def test_selection_resume_and_baseline_diff(tmp_path: Path) -> None:
    """筛选、结果续跑和 baseline 新增/修复失败应可追溯。"""
    case = load_cases(EXAMPLE)[0]
    selected = select_cases([case], case_ids={case.case_id}, tags={"routing"})
    assert selected == [case]
    assert select_cases([case], tags={"memory"}) == []

    config = load_run_config(CONFIG)
    adapter = GraphAdapter(config, FixtureRepository.from_json(FIXTURES).execute)
    original = _run([case], adapter)
    report_path = tmp_path / "resume.json"
    report_path.write_text(json.dumps({
        "results": [result.model_dump(mode="json") for result in original]
    }), encoding="utf-8")
    resumed = load_completed_results(report_path)

    def must_not_run(*_args):
        raise AssertionError("resume should skip completed case")

    rerun = run_cases(
        [case], adapter=GraphAdapter(config, must_not_run),
        scorers=ScorerRegistry([ExpectedBehaviorScorer()]),
        run_id="run-resume", model_id="mock", code_version="abc", prompt_version="abc",
        resume_results=resumed,
    )
    assert rerun == resumed

    summary = aggregate_results(rerun)
    diff = compare_baseline(summary, {"failed_cases": ["old_failure"], "metric_macro": {}})
    assert diff["fixed_failures"] == ["old_failure"]
    assert diff["new_failures"] == []


def test_scorer_registry_rejects_duplicate_names() -> None:
    """重复 Scorer 名称必须在运行前失败。"""
    registry = ScorerRegistry([ExpectedBehaviorScorer()])
    try:
        registry.register(ExpectedBehaviorScorer())
    except ValueError as exc:
        assert "Scorer 名称重复" in str(exc)
    else:
        raise AssertionError("duplicate scorer should fail")
