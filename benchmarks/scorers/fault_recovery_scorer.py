"""fault_recovery_scorer — PostgreSQL 与外部服务故障恢复评分

所属层：tests
依赖：benchmarks.scorers.base
对接算法层：N/A
"""
from benchmarks.adapters.base import AdapterResponse
from benchmarks.scorers.base import BaseScorer, ScoreBundle
from benchmarks.shared.result_models import EvalCase, GateResult, MetricResult


class FaultRecoveryScorer(BaseScorer):
    """计算故障安全降级、恢复一致性和隔离清理指标。"""

    name = "fault_recovery"

    def score(self, case: EvalCase, response: AdapterResponse) -> ScoreBundle:
        """生成 T14 故障恢复指标和硬门禁。"""
        observation = response.observations.get("fault_recovery", {})
        safe_degraded = bool(observation.get("safe_degraded"))
        no_leak = bool(observation.get("no_cross_domain_leak"))
        no_fabrication = bool(observation.get("no_fabrication"))
        recovered = bool(observation.get("recovered"))
        data_consistent = bool(observation.get("data_consistent"))
        cleanup_ok = bool(observation.get("cleanup_ok"))
        production_untouched = bool(observation.get("production_untouched"))

        recovery_required = "recovered" in case.tags or observation.get("failure") in {
            "service_restart", "cross_process_read", "pool_exhausted",
            "permission_denied", "401_then_refresh",
        }
        recovery_valid = (recovered if recovery_required else True) and data_consistent
        isolation_safe = no_leak and no_fabrication
        cleanup_safe = cleanup_ok and production_untouched

        return ScoreBundle(
            metrics=[
                MetricResult(name="safe_degradation", score=float(safe_degraded)),
                MetricResult(name="isolation_safety", score=float(isolation_safe)),
                MetricResult(name="recovery_consistency", score=float(recovery_valid)),
                MetricResult(name="cleanup_integrity", score=float(cleanup_safe)),
            ],
            gates=[
                GateResult(name="unsafe_degradation", violated=not safe_degraded),
                GateResult(name="cross_domain_leak", violated=not no_leak),
                GateResult(name="fabricated_after_failure", violated=not no_fabrication),
                GateResult(
                    name="recovery_inconsistent",
                    violated=not recovery_valid,
                    evidence_summary=str(observation.get("evidence", "")),
                ),
                GateResult(name="namespace_or_production_pollution", violated=not cleanup_safe),
            ],
        )
