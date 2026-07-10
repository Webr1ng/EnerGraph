"""test_eval_governance — T15 企业基线、阈值和发布治理回归

所属层：tests
依赖：pytest, benchmarks.shared
对接算法层：N/A
"""
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from benchmarks.shared.config_models import load_run_config
from benchmarks.shared.governance import (
    BaselineUpdateRecord,
    ReleaseSignoff,
    ThresholdChangeRecord,
    classify_baseline_diff,
    validate_release_signoff,
)
from benchmarks.shared.run_metadata import build_run_manifest


def test_baseline_update_requires_independent_approval() -> None:
    """baseline 更新必须有独立审批人，不能自批。"""
    with pytest.raises(ValueError, match="申请人和审批人不能相同"):
        BaselineUpdateRecord(
            baseline_name="routing_v0_1",
            reason="新增稳定代表集后刷新 baseline",
            requested_by="周溥林",
            approved_by="周溥林",
            run_id="run-001",
            new_summary={"hard_gate_passed": True},
        )


def test_baseline_update_rejects_hard_gate_failure() -> None:
    """硬门禁失败结果不得被批准为 baseline。"""
    with pytest.raises(ValueError, match="硬门禁失败"):
        BaselineUpdateRecord(
            baseline_name="security_v0_1",
            reason="错误尝试接受安全失败结果",
            requested_by="周溥林",
            approved_by="魏博源",
            run_id="run-002",
            new_summary={"hard_gate_passed": False},
        )


def test_classify_baseline_diff_separates_metric_change_from_gate_regression() -> None:
    """普通指标波动和硬门禁回归必须分开呈现。"""
    metric_only = classify_baseline_diff(
        {"failed_cases": [], "gate_violations": {}, "metric_macro": {"quality": 0.9}},
        {"failed_cases": [], "metric_macro": {"quality": 0.95}},
    )
    gate_regression = classify_baseline_diff(
        {
            "failed_cases": ["security_prompt_leak_001"],
            "gate_violations": {"secret_leakage": 1},
            "metric_macro": {"safe": 0.9},
        },
        {"failed_cases": [], "metric_macro": {"safe": 1.0}},
    )

    assert metric_only["metric_only_change"] is True
    assert metric_only["hard_gate_regression"] is False
    assert gate_regression["hard_gate_regression"] is True
    assert gate_regression["metric_only_change"] is False


def test_threshold_change_direction_is_auditable() -> None:
    """阈值收紧/放宽方向必须可审计。"""
    relaxed = ThresholdChangeRecord(
        metric_name="final_answer_accuracy",
        old_threshold=0.9,
        new_threshold=0.85,
        reason="首次真实模型基线确认后调整回答质量阈值",
        approved_by="负责人",
    )
    tightened = ThresholdChangeRecord(
        metric_name="tool_call_f1",
        old_threshold=0.95,
        new_threshold=0.98,
        reason="Tool 调用稳定后提高发布要求",
        approved_by="负责人",
    )

    assert relaxed.direction == "relax"
    assert tightened.direction == "tighten"


def test_release_signoff_requires_production_manifest() -> None:
    """发布签字必须能追溯数据集版本，且默认要求 Production 清单。"""
    config = load_run_config("benchmarks/configs/fast.yaml")
    manifest = build_run_manifest(
        run_id="fast-only",
        config=config,
        dataset_versions={"routing": "0.1"},
        model_id="mock",
        project_root=None,
        started_at=datetime(2026, 7, 9, tzinfo=timezone.utc),
    )
    signoff = ReleaseSignoff(
        version="v0.1",
        signer="周溥林",
        manifests=[manifest],
    )

    assert validate_release_signoff(signoff) == ["缺少 Production 运行清单"]


def test_run_manifest_prompt_version_marks_dirty_eval_logic(monkeypatch) -> None:
    """未提交的 Prompt/Harness 变更必须进入版本标识，便于复盘同 commit 评测。"""
    def fake_git_output(args, _cwd):
        if args == ["rev-parse", "HEAD"]:
            return "abcdef1234567890"
        if args == ["status", "--porcelain"]:
            return " M src/config/prompts/main_graph.yaml"
        if args[:2] == ["diff", "--"]:
            return "diff --git a/src/config/prompts/main_graph.yaml b/src/config/prompts/main_graph.yaml"
        return "unknown"

    monkeypatch.setattr("benchmarks.shared.run_metadata._git_output", fake_git_output)
    config = load_run_config("benchmarks/configs/fast.yaml")

    manifest = build_run_manifest(
        run_id="dirty-version",
        config=config,
        dataset_versions={"routing": "0.1"},
        model_id="mock",
        project_root=Path("."),
        started_at=datetime(2026, 7, 9, tzinfo=timezone.utc),
    )

    assert manifest.prompt_version.startswith("git:abcdef123456+dirty:")


def test_ci_matrix_defines_pr_daily_and_release_tiers() -> None:
    """T15 CI 矩阵必须包含每提交、每日和发布前三档。"""
    matrix_path = Path("benchmarks/configs/ci_matrix.yaml")
    matrix = yaml.safe_load(matrix_path.read_text(encoding="utf-8"))

    assert set(matrix["tiers"]) == {"pr", "daily", "release"}
    assert matrix["tiers"]["pr"]["network_allowed"] is False
    assert matrix["tiers"]["release"]["required"] is True
    assert "run_manifest.json" in matrix["signoff"]["required_artifacts"]
    assert {"memory", "retrieval", "model"}.issubset(matrix["experiments"])
