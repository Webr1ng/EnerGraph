"""test_fault_recovery_benchmark — T14 故障恢复 MiniBench 回归

所属层：tests
依赖：pytest, benchmarks
对接算法层：N/A
"""
import json
from pathlib import Path

from benchmarks.adapters.fault_recovery_adapter import create_fault_recovery_production_executor
from benchmarks.adapters.base import AdapterResponse
from benchmarks.datasets.fault_recovery.v0_1 import load_fault_recovery_cases
from benchmarks.runners.run_fault_recovery import main as run_fault_recovery_main
from benchmarks.scorers.fault_recovery_scorer import FaultRecoveryScorer
from benchmarks.shared.config_models import load_run_config


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


def test_fault_recovery_production_config_uses_real_executor(monkeypatch, tmp_path: Path) -> None:
    """Production 配置应进入真实执行器路径，而不是固定 fixture。"""
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
    monkeypatch.setenv("LOCAL_MODEL", "production-model")
    evidence = {
        "fault_illegal_tool_call_001": {
            "component": "tool_router",
            "failure": "illegal_tool_call",
            "safe_degraded": True,
            "no_cross_domain_leak": True,
            "no_fabrication": True,
            "recovered": False,
            "data_consistent": True,
            "cleanup_ok": True,
            "production_untouched": True,
            "evidence": "external production injector verified illegal tool rejection",
        },
    }
    evidence_path = tmp_path / "fault_evidence.json"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    monkeypatch.setenv("EVAL_FAULT_RECOVERY_EVIDENCE_PATH", str(evidence_path))

    code = run_fault_recovery_main([
        "--config", "benchmarks/configs/fault_recovery_production.yaml",
        "--case-id", "fault_illegal_tool_call_001",
        "--output-dir", str(tmp_path / "production_fault_report"),
        "--run-id", "fault-production-test",
    ])

    assert code == 0
    summary = (tmp_path / "production_fault_report" / "summary.md").read_text(encoding="utf-8")
    assert "Production" not in summary
    assert "`production`" in summary


def test_fault_recovery_production_executor_fails_without_external_injection(monkeypatch) -> None:
    """需要真实故障注入的 case 缺证据时必须失败，不能伪造成通过。"""
    monkeypatch.delenv("EVAL_FAULT_RECOVERY_EVIDENCE_PATH", raising=False)
    environment = {
        "EVAL_FAULT_RECOVERY_PRODUCTION": "1",
        "EVAL_NAMESPACE_PREFIX": "eval_fault_recovery_production",
        "LOCAL_BASE_URL": "http://model.invalid/v1",
        "LOCAL_MODEL": "model",
        "MEMORY_POSTGRES_DSN": "postgresql://user:pass@db.invalid/eval",
        "FUCA_API_BASE_URL": "https://api.invalid",
        "FUCA_TENANT_ID": "tenant",
    }
    config = load_run_config("benchmarks/configs/fault_recovery_production.yaml", environment=environment)
    case = next(case for case in load_fault_recovery_cases() if case.case_id == "fault_llm_timeout_001")

    response = create_fault_recovery_production_executor()(case, config, "eval_fault_recovery_production/test")
    bundle = FaultRecoveryScorer().score(case, response)

    observation = response.observations["fault_recovery"]
    assert observation["safe_degraded"] is False
    assert "EVAL_FAULT_RECOVERY_EVIDENCE_PATH" in observation["evidence"]
    assert any(gate.violated for gate in bundle.gates)


def test_fault_recovery_production_executor_accepts_external_evidence(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """真实故障注入器的脱敏证据可驱动 Production case 通过评分。"""
    case = next(case for case in load_fault_recovery_cases() if case.case_id == "fault_llm_timeout_001")
    output = case.fixtures["fault_recovery_output"]
    evidence_path = tmp_path / "fault_evidence.json"
    evidence_path.write_text(json.dumps({case.case_id: output}), encoding="utf-8")
    monkeypatch.setenv("EVAL_FAULT_RECOVERY_EVIDENCE_PATH", str(evidence_path))
    config = load_run_config(
        "benchmarks/configs/fault_recovery_production.yaml",
        environment={
            "EVAL_FAULT_RECOVERY_PRODUCTION": "1",
            "EVAL_NAMESPACE_PREFIX": "eval_fault_recovery_production",
            "LOCAL_BASE_URL": "http://model.invalid/v1",
            "LOCAL_MODEL": "model",
            "MEMORY_POSTGRES_DSN": "postgresql://user:pass@db.invalid/eval",
            "FUCA_API_BASE_URL": "https://api.invalid",
            "FUCA_TENANT_ID": "tenant",
        },
    )

    response = create_fault_recovery_production_executor()(case, config, "eval_fault_recovery_production/test")
    bundle = FaultRecoveryScorer().score(case, response)

    assert response.observations["fault_recovery"] == output
    assert all(not gate.violated for gate in bundle.gates)
