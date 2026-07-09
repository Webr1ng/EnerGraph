"""run_faithfulness — 数据忠实度与拒答 MiniBench v0.1 运行入口

所属层：tests
依赖：benchmarks.adapters, benchmarks.datasets.faithfulness, benchmarks.scorers
对接算法层：N/A
"""
import argparse
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

from benchmarks.adapters import (
    FaithfulnessAdapter,
    create_faithfulness_fixture_executor,
    create_local_llm_faithfulness_executor,
)
from benchmarks.datasets.faithfulness.v0_1 import load_faithfulness_cases
from benchmarks.runners.run_all import exit_code_for_results, run_cases, select_cases
from benchmarks.scorers import FaithfulnessScorer, ScorerRegistry
from benchmarks.shared.config_models import load_run_config
from benchmarks.shared.report_generator import load_baseline, write_report
from benchmarks.shared.run_metadata import build_run_manifest


def main(argv: Optional[Sequence[str]] = None) -> int:
    """运行数据忠实度 MiniBench 并返回 CI 退出码。"""
    parser = argparse.ArgumentParser(description="EnerGraph Faithfulness MiniBench")
    parser.add_argument("--config", default="benchmarks/configs/fast.yaml")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--tag", action="append")
    parser.add_argument("--case-id", action="append")
    parser.add_argument("--baseline")
    parser.add_argument("--run-id")
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[2]
    config = load_run_config(args.config)
    cases = select_cases(
        load_faithfulness_cases(),
        case_ids=set(args.case_id or []), tags=set(args.tag or []),
    )
    if not cases:
        raise ValueError("筛选后没有 Faithfulness 案例")
    run_id = args.run_id or datetime.now(timezone.utc).strftime("faithfulness-%Y%m%dT%H%M%SZ")
    if config.mode == "fast":
        executor = create_faithfulness_fixture_executor()
        model_id = "fixed-evidence-v0.1"
    else:
        from src.config.settings import settings as _settings

        _ = _settings.model.provider
        executor = create_local_llm_faithfulness_executor()
        model_id = os.getenv("LOCAL_MODEL", "unreported-real-model")
    manifest = build_run_manifest(
        run_id=run_id, config=config, dataset_versions={"faithfulness": "0.1"},
        model_id=model_id, project_root=root,
    )
    adapter = FaithfulnessAdapter(config, executor)
    results = run_cases(
        cases, adapter=adapter, scorers=ScorerRegistry([FaithfulnessScorer()]),
        run_id=run_id, model_id=model_id,
        code_version=manifest.git_commit, prompt_version=manifest.prompt_version,
    )
    manifest.finished_at = datetime.now(timezone.utc)
    baseline = load_baseline(args.baseline) if args.baseline else None
    write_report(args.output_dir, results, manifest, baseline)
    return exit_code_for_results(results)


if __name__ == "__main__":
    raise SystemExit(main())
