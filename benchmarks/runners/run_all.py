"""run_all — Eval 案例筛选、失败隔离、续跑、评分与报告入口

所属层：tests
依赖：argparse, benchmarks.adapters, benchmarks.scorers, benchmarks.shared
对接算法层：N/A
"""
import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Set

from benchmarks.adapters import GraphAdapter, create_energraph_executor
from benchmarks.adapters.base import AdapterResponse, BaseAdapter
from benchmarks.fixtures import FixtureRepository
from benchmarks.scorers import ExpectedBehaviorScorer, ScorerRegistry
from benchmarks.shared.case_loader import load_cases
from benchmarks.shared.config_models import EvalRunConfig, load_run_config
from benchmarks.shared.report_generator import load_baseline, write_report
from benchmarks.shared.result_models import EvalCase, EvalResult, GateResult
from benchmarks.shared.run_metadata import build_run_manifest


def select_cases(
    cases: Iterable[EvalCase],
    *,
    case_ids: Optional[Set[str]] = None,
    tags: Optional[Set[str]] = None,
    categories: Optional[Set[str]] = None,
) -> List[EvalCase]:
    """按 case_id、tag 和 category 交集筛选案例。"""
    selected = []
    for case in cases:
        if case_ids and case.case_id not in case_ids:
            continue
        if tags and not tags.intersection(case.tags):
            continue
        if categories and case.category not in categories:
            continue
        selected.append(case)
    return selected


def load_completed_results(path: Path | str) -> List[EvalResult]:
    """读取已有 results.json，供断点续跑跳过成功或失败案例。"""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    raw_results = payload.get("results", payload) if isinstance(payload, dict) else payload
    return [EvalResult.model_validate(item) for item in raw_results]


def run_cases(
    cases: Sequence[EvalCase],
    *,
    adapter: BaseAdapter,
    scorers: ScorerRegistry,
    run_id: str,
    model_id: str,
    code_version: str,
    prompt_version: str,
    resume_results: Sequence[EvalResult] = (),
) -> List[EvalResult]:
    """逐案例执行、隔离异常并返回稳定顺序的 EvalResult。"""
    existing = {result.case_id: result for result in resume_results}
    results = dict(existing)
    for case in cases:
        if case.case_id in existing:
            continue
        started = time.perf_counter()
        try:
            response = adapter.run(case)
            bundle = scorers.score(case, response)
            result = EvalResult(
                run_id=run_id,
                case_id=case.case_id,
                mode=adapter.config.mode,
                model_id=model_id,
                prompt_version=prompt_version,
                code_version=code_version,
                actual_intents=response.actual_intents,
                actual_agent=response.actual_agent,
                actual_skill=response.actual_skill,
                tool_calls=response.tool_calls,
                answer=response.answer,
                protocol_events=response.protocol_events,
                metrics=bundle.metrics,
                gates=bundle.gates,
                latency_ms=(time.perf_counter() - started) * 1000,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                error=response.error,
                evidence_summary=response.evidence_summary,
                observations=response.observations,
            )
        except Exception as exc:
            result = EvalResult(
                run_id=run_id,
                case_id=case.case_id,
                mode=adapter.config.mode,
                model_id=model_id,
                prompt_version=prompt_version,
                code_version=code_version,
                latency_ms=(time.perf_counter() - started) * 1000,
                error=f"{type(exc).__name__}: {exc}",
                gates=[GateResult(
                    name="adapter_exception", violated=True,
                    evidence_summary=f"{type(exc).__name__}: {exc}",
                )],
            )
        results[case.case_id] = result
    return [results[case_id] for case_id in sorted(results)]


def exit_code_for_results(results: Sequence[EvalResult]) -> int:
    """任一硬门禁或执行错误存在时返回 1，否则返回 0。"""
    return 1 if any(result.error or not result.hard_gate_passed for result in results) else 0


def _build_adapter(config: EvalRunConfig, project_root: Path) -> tuple[BaseAdapter, str]:
    """按模式构建最小 GraphAdapter；Fast 固定 Fixture，其他模式真实图。"""
    if config.mode == "fast":
        if not config.fixture_path:
            raise ValueError("Fast 配置缺少 fixture_path")
        repository = FixtureRepository.from_json(project_root / config.fixture_path)
        return GraphAdapter(config, repository.execute), "mock-scripted-v0.1"
    model_id = os.getenv("LOCAL_MODEL", "unreported-real-model")
    return GraphAdapter(config, create_energraph_executor()), model_id


def main(argv: Optional[Sequence[str]] = None) -> int:
    """运行命令行评测并返回适合 CI 的退出码。"""
    parser = argparse.ArgumentParser(description="EnerGraph Eval runner")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--case-id", action="append")
    parser.add_argument("--tag", action="append")
    parser.add_argument("--category", action="append")
    parser.add_argument("--resume")
    parser.add_argument("--baseline")
    parser.add_argument("--run-id")
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[2]
    config = load_run_config(args.config)
    cases = select_cases(
        load_cases(args.dataset),
        case_ids=set(args.case_id or []), tags=set(args.tag or []),
        categories=set(args.category or []),
    )
    if not cases:
        raise ValueError("筛选后没有可运行案例")
    adapter, model_id = _build_adapter(config, root)
    run_id = args.run_id or datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%SZ")
    manifest = build_run_manifest(
        run_id=run_id, config=config,
        dataset_versions={cases[0].category: cases[0].version}, model_id=model_id,
        project_root=root,
    )
    resume = load_completed_results(args.resume) if args.resume else []
    results = run_cases(
        cases,
        adapter=adapter,
        scorers=ScorerRegistry([ExpectedBehaviorScorer()]),
        run_id=run_id,
        model_id=model_id,
        code_version=manifest.git_commit,
        prompt_version=manifest.prompt_version,
        resume_results=resume,
    )
    manifest.finished_at = datetime.now(timezone.utc)
    baseline = load_baseline(args.baseline) if args.baseline else None
    write_report(args.output_dir, results, manifest, baseline)
    return exit_code_for_results(results)


if __name__ == "__main__":
    raise SystemExit(main())
