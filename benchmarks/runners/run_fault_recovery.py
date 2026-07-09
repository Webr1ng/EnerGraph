"""run_fault_recovery — PostgreSQL 与外部服务故障恢复 MiniBench v0.1 入口

所属层：tests
依赖：benchmarks.adapters, benchmarks.datasets.fault_recovery, benchmarks.scorers
对接算法层：N/A
"""
import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

from benchmarks.adapters import FaultRecoveryAdapter, create_fault_recovery_fixture_executor
from benchmarks.datasets.fault_recovery.v0_1 import load_fault_recovery_cases
from benchmarks.runners.run_all import exit_code_for_results, run_cases, select_cases
from benchmarks.scorers import FaultRecoveryScorer, ScorerRegistry
from benchmarks.shared.config_models import load_run_config
from benchmarks.shared.report_generator import load_baseline, write_report
from benchmarks.shared.run_metadata import build_run_manifest


def _ensure_supported_fault_recovery_mode(config) -> None:
    """防止 T14 Production 使用合成 fixture 冒充真实验收。

    Args:
        config: 已加载的 Eval 运行配置。

    Raises:
        RuntimeError: Production 模式尚无真实故障注入执行器时抛出。
    """
    if config.mode == "production":
        raise RuntimeError(
            "T14 Production 故障恢复不能使用 fixed fixture executor；"
            "请在独立测试环境接入真实 PostgreSQL/福加 API/LLM 故障注入执行器后再运行，"
            "不得把 Fast/Standard 合成结果报告为 Production 验收。"
        )


def main(argv: Optional[Sequence[str]] = None) -> int:
    """运行 Fault Recovery MiniBench 并返回 CI 退出码。"""
    parser = argparse.ArgumentParser(description="EnerGraph Fault Recovery MiniBench")
    parser.add_argument("--config", default="benchmarks/configs/fast.yaml")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--tag", action="append")
    parser.add_argument("--case-id", action="append")
    parser.add_argument("--baseline")
    parser.add_argument("--run-id")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[2]
    config = load_run_config(args.config)
    _ensure_supported_fault_recovery_mode(config)
    cases = select_cases(load_fault_recovery_cases(), case_ids=set(args.case_id or []), tags=set(args.tag or []))
    if not cases:
        raise ValueError("筛选后没有 Fault Recovery 案例")
    run_id = args.run_id or datetime.now(timezone.utc).strftime("fault-recovery-%Y%m%dT%H%M%SZ")
    model_id = "fixed-fault-recovery-v0.1"
    manifest = build_run_manifest(run_id=run_id, config=config, dataset_versions={"fault_recovery": "0.1"}, model_id=model_id, project_root=root)
    results = run_cases(
        cases, adapter=FaultRecoveryAdapter(config, create_fault_recovery_fixture_executor()),
        scorers=ScorerRegistry([FaultRecoveryScorer()]), run_id=run_id, model_id=model_id,
        code_version=manifest.git_commit, prompt_version=manifest.prompt_version,
    )
    manifest.finished_at = datetime.now(timezone.utc)
    write_report(args.output_dir, results, manifest, load_baseline(args.baseline) if args.baseline else None)
    return exit_code_for_results(results)


if __name__ == "__main__":
    raise SystemExit(main())
