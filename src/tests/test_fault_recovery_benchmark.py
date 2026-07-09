"""test_fault_recovery_benchmark — T14 故障恢复 MiniBench 回归

所属层：tests
依赖：pytest, benchmarks
对接算法层：N/A
"""
from pathlib import Path

import pytest

from benchmarks.adapters.base import AdapterResponse
from benchmarks.datasets.fault_recovery.v0_1 import load_fault_recovery_cases
from benchmarks.runners.run_fault_recovery import main as run_fault_recovery_main
from benchmarks.scorers.fault_recovery_scorer import FaultRecoveryScorer


def test_fault_recovery_dataset_loads_ten_cases() -> None:
    """T14 v0.1 覆盖 10 个 PostgreSQL/外部服务故障基础场景。"""
    cases = load_fault_recovery_cases()

    assert len(cases) == 10
    assert {case.category for case in cases} == {"fault_recovery"}
    assert {"postgres", "fuca_api", "llm", "tool"}.issubset(
        {tag for case in cases for tag in case.tags}
    )


def test_fault_recovery_positive_cases_pass() -> None:
    """固定正例不触发任何故障恢复硬门禁。"""
    scorer = FaultRecoveryScorer()

    for case in load_fault_recovery_cases():
        response = AdapterResponse(
            observations={"fault_recovery": case.fixtures["fault_recovery_output"]},
        )
        bundle = scorer.score(case, response)
        assert all(not gate.violated for gate in bundle.gates), case.case_id


def test_fault_recovery_negative_observation_triggers_gates() -> None:
    """泄漏、编造、恢复失败和污染必须被独立捕获。"""
    case = load_fault_recovery_cases()[0]
    response = AdapterResponse(observations={"fault_recovery": {
        "safe_degraded": False,
        "no_cross_domain_leak": False,
        "no_fabrication": False,
        "recovered": False,
        "data_consistent": False,
        "cleanup_ok": False,
        "production_untouched": False,
    }})

    bundle = FaultRecoveryScorer().score(case, response)
    violated = {gate.name for gate in bundle.gates if gate.violated}

    assert {
        "unsafe_degradation",
        "cross_domain_leak",
        "fabricated_after_failure",
        "recovery_inconsistent",
        "namespace_or_production_pollution",
    } == violated


def test_fault_recovery_runner_writes_report(tmp_path: Path) -> None:
    """Fast runner 能写出通过报告并返回 0。"""
    code = run_fault_recovery_main([
        "--output-dir", str(tmp_path / "fault_report"),
        "--run-id", "fault-test",
    ])

    assert code == 0
    assert (tmp_path / "fault_report" / "summary.md").is_file()


def test_fault_recovery_production_config_cannot_use_fixture_executor(monkeypatch, tmp_path: Path) -> None:
    """Production 配置不能误用 Fast fixture 执行器并产出伪生产验收。"""
    for key in (
        "EVAL_FAULT_RECOVERY_PRODUCTION",
        "EVAL_NAMESPACE_PREFIX",
        "LOCAL_BASE_URL",
        "LOCAL_MODEL",
        "MEMORY_POSTGRES_DSN",
        "FUCA_API_BASE_URL",
        "FUCA_TENANT_ID",
    ):
        monkeypatch.setenv(key, "present")

    with pytest.raises(RuntimeError, match="不能使用 fixed fixture executor"):
        run_fault_recovery_main([
            "--config", "benchmarks/configs/fault_recovery_production.yaml",
            "--output-dir", str(tmp_path / "production_fault_report"),
            "--run-id", "fault-production-test",
        ])
