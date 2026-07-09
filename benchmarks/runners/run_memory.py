"""run_memory — Memory MiniBench v0.1 Fast/Store 运行入口

所属层：tests
依赖：benchmarks.adapters, benchmarks.datasets.memory, benchmarks.scorers
对接算法层：N/A
"""
import argparse
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

from benchmarks.adapters import (
    MemoryAdapter,
    create_memory_benchmark_executor,
    memory_namespace_cleaner,
)
from benchmarks.datasets.memory.v0_1 import load_memory_cases
from benchmarks.runners.run_all import exit_code_for_results, run_cases, select_cases
from benchmarks.scorers import MemoryScorer, ScorerRegistry
from benchmarks.shared.config_models import load_run_config
from benchmarks.shared.report_generator import load_baseline, write_report
from benchmarks.shared.run_metadata import build_run_manifest


def main(argv: Optional[Sequence[str]] = None) -> int:
    """运行 Memory MiniBench 并返回 CI 退出码。"""
    parser = argparse.ArgumentParser(description="EnerGraph Memory MiniBench")
    parser.add_argument("--config", default="benchmarks/configs/fast.yaml")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--tag", action="append")
    parser.add_argument("--case-id", action="append")
    parser.add_argument("--baseline")
    parser.add_argument("--run-id")
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[2]
    from src.config.settings import settings
    from src.memory.store import reset_memory_store

    config = load_run_config(args.config)
    if config.store.kind == "postgres":
        settings.memory.use_postgres_store = True
        settings.memory.enabled = True
        settings.memory.postgres_dsn = os.environ["MEMORY_POSTGRES_DSN"]
        settings.memory.namespace_prefix = config.options.namespace_prefix
        settings.memory.env = "eval"
        settings.memory.postgres_setup_enabled = False
    else:
        settings.memory.use_postgres_store = False
        settings.memory.enabled = False
        settings.memory.demo_file_store_enabled = False
        settings.memory.namespace_prefix = config.options.namespace_prefix
        settings.memory.env = "eval"
    reset_memory_store()
    cases = select_cases(
        load_memory_cases(),
        case_ids=set(args.case_id or []), tags=set(args.tag or []),
    )
    if not cases:
        raise ValueError("筛选后没有 Memory 案例")
    run_id = args.run_id or datetime.now(timezone.utc).strftime("memory-%Y%m%dT%H%M%SZ")
    manifest = build_run_manifest(
        run_id=run_id, config=config, dataset_versions={"memory": "0.1"},
        model_id="deterministic-memory-store", project_root=root,
    )
    adapter = MemoryAdapter(
        config, create_memory_benchmark_executor(),
        namespace_cleaner=memory_namespace_cleaner,
    )
    results = run_cases(
        cases, adapter=adapter, scorers=ScorerRegistry([MemoryScorer()]),
        run_id=run_id, model_id="deterministic-memory-store",
        code_version=manifest.git_commit, prompt_version=manifest.prompt_version,
    )
    manifest.finished_at = datetime.now(timezone.utc)
    baseline = load_baseline(args.baseline) if args.baseline else None
    write_report(args.output_dir, results, manifest, baseline)
    return exit_code_for_results(results)


if __name__ == "__main__":
    raise SystemExit(main())
