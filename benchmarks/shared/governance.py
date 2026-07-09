"""governance — 企业评测基线、阈值和发布治理规则

所属层：tests
依赖：datetime, pydantic, benchmarks.shared
对接算法层：N/A
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from benchmarks.shared.report_generator import compare_baseline
from benchmarks.shared.result_models import RunManifest


class BaselineUpdateRecord(BaseModel):
    """一次 baseline 更新审批记录。"""

    baseline_name: str = Field(min_length=1)
    reason: str = Field(min_length=10)
    requested_by: str = Field(min_length=1)
    approved_by: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    old_summary: Dict[str, Any] = Field(default_factory=dict)
    new_summary: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def validate_auditability(self) -> "BaselineUpdateRecord":
        """baseline 更新必须有理由、审批人，且不能接受硬门禁失败结果。"""
        if self.requested_by == self.approved_by:
            raise ValueError("baseline 更新申请人和审批人不能相同")
        if not self.new_summary.get("hard_gate_passed", False):
            raise ValueError("禁止将硬门禁失败结果更新为 baseline")
        return self


class ThresholdChangeRecord(BaseModel):
    """一次指标阈值变更记录。"""

    metric_name: str = Field(min_length=1)
    old_threshold: float = Field(ge=0, le=1)
    new_threshold: float = Field(ge=0, le=1)
    reason: str = Field(min_length=10)
    approved_by: str = Field(min_length=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def direction(self) -> Literal["tighten", "relax", "unchanged"]:
        """返回阈值变化方向。"""
        if self.new_threshold > self.old_threshold:
            return "tighten"
        if self.new_threshold < self.old_threshold:
            return "relax"
        return "unchanged"


class ReleaseSignoff(BaseModel):
    """发布签字检查所需的最小证据。"""

    version: str = Field(min_length=1)
    signer: str = Field(min_length=1)
    manifests: List[RunManifest] = Field(min_length=1)
    unresolved_hard_gates: int = Field(default=0, ge=0)
    production_manifest_required: bool = True


def classify_baseline_diff(current_summary: Dict[str, Any], baseline_summary: Dict[str, Any]) -> Dict[str, Any]:
    """区分硬门禁新增失败、普通指标波动和已修复失败。

    Args:
        current_summary: 当前运行 summary。
        baseline_summary: 已批准 baseline summary。

    Returns:
        治理分类结果。
    """
    diff = compare_baseline(current_summary, baseline_summary)
    gate_violations = current_summary.get("gate_violations", {}) or {}
    new_failures = diff.get("new_failures", [])
    hard_gate_regression = bool(gate_violations or new_failures)
    return {
        **diff,
        "hard_gate_regression": hard_gate_regression,
        "metric_only_change": not hard_gate_regression and bool(diff.get("metric_delta")),
    }


def validate_release_signoff(signoff: ReleaseSignoff) -> List[str]:
    """验证发布签字是否具备可追溯运行清单和 Production 证据。

    Args:
        signoff: 发布签字证据。

    Returns:
        错误列表；空列表表示可签字。
    """
    errors: List[str] = []
    if signoff.unresolved_hard_gates:
        errors.append("存在未解决硬门禁")
    if any(manifest.git_commit == "unknown" for manifest in signoff.manifests):
        errors.append("存在不可追溯 git_commit")
    if any(not manifest.dataset_versions for manifest in signoff.manifests):
        errors.append("存在缺失数据集版本的运行清单")
    if signoff.production_manifest_required and not any(
        manifest.mode == "production" for manifest in signoff.manifests
    ):
        errors.append("缺少 Production 运行清单")
    return errors
