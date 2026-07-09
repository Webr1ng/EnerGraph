"""run_ui_contract — SSE、UIAction 与 DataCard MiniBench v0.1 入口

所属层：tests
依赖：benchmarks.adapters, benchmarks.datasets.ui_contract, benchmarks.scorers
对接算法层：N/A
"""
import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

from benchmarks.adapters import UIContractAdapter, create_ui_contract_fixture_executor
from benchmarks.datasets.ui_contract.v0_1 import load_ui_contract_cases
from benchmarks.runners.run_all import exit_code_for_results, run_cases, select_cases
from benchmarks.scorers import ScorerRegistry, UIContractScorer
from benchmarks.shared.config_models import load_run_config
from benchmarks.shared.report_generator import load_baseline, write_report
from benchmarks.shared.run_metadata import build_run_manifest


def main(argv: Optional[Sequence[str]] = None) -> int:
    """运行 UI Contract MiniBench 并返回 CI 退出码。"""
    parser = argparse.ArgumentParser(description="EnerGraph UI Contract MiniBench")
    parser.add_argument("--config", default="benchmarks/configs/fast.yaml")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--tag", action="append")
    parser.add_argument("--case-id", action="append")
    parser.add_argument("--baseline")
    parser.add_argument("--run-id")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[2]
    config = load_run_config(args.config)
    cases = select_cases(load_ui_contract_cases(), case_ids=set(args.case_id or []), tags=set(args.tag or []))
    if not cases:
        raise ValueError("筛选后没有 UI Contract 案例")
    run_id = args.run_id or datetime.now(timezone.utc).strftime("ui-contract-%Y%m%dT%H%M%SZ")
    model_id = "fixed-ui-contract-v0.1"
    manifest = build_run_manifest(run_id=run_id, config=config, dataset_versions={"ui_contract": "0.1"}, model_id=model_id, project_root=root)
    results = run_cases(
        cases, adapter=UIContractAdapter(config, create_ui_contract_fixture_executor()),
        scorers=ScorerRegistry([UIContractScorer()]), run_id=run_id, model_id=model_id,
        code_version=manifest.git_commit, prompt_version=manifest.prompt_version,
    )
    manifest.finished_at = datetime.now(timezone.utc)
    write_report(args.output_dir, results, manifest, load_baseline(args.baseline) if args.baseline else None)
    return exit_code_for_results(results)


if __name__ == "__main__":
    raise SystemExit(main())
