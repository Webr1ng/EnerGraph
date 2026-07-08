"""memory_scorer — Memory MiniBench 指标与零容忍门禁

所属层：tests
依赖：benchmarks.scorers.base
对接算法层：N/A
"""
from benchmarks.adapters.base import AdapterResponse
from benchmarks.scorers.base import BaseScorer, ScoreBundle
from benchmarks.shared.result_models import EvalCase, GateResult, MetricResult


def _binary_prf(expected: bool, actual_count: int) -> tuple[float, float, float]:
    """计算单案例写入 precision、recall、F1。"""
    actual = actual_count > 0
    true_positive = int(expected and actual)
    precision = true_positive / actual_count if actual_count else (1.0 if not expected else 0.0)
    recall = true_positive if expected else (1.0 if not actual else 0.0)
    f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
    return precision, recall, f1


class MemoryScorer(BaseScorer):
    """评估记忆写入、检索、更新、隔离和时效。"""

    name = "memory"

    def score(self, case: EvalCase, response: AdapterResponse) -> ScoreBundle:
        """根据 memory observations 生成 T4 指标和硬门禁。"""
        observation = response.observations.get("memory", {})
        writes = observation.get("writes", [])
        expected_write = bool(case.expected.memory_should_write)
        precision, recall, f1 = _binary_prf(expected_write, len(writes))
        first_write = writes[0] if writes else {}
        type_accuracy = (
            1.0 if case.expected.expected_memory_type is None
            else float(first_write.get("memory_type") == case.expected.expected_memory_type)
        )
        key_accuracy = (
            1.0 if case.expected.expected_memory_key is None
            else float(first_write.get("memory_key") == case.expected.expected_memory_key)
        )

        expected_aliases = case.expected.expected_retrieved_aliases
        retrieved_aliases = observation.get("retrieved_aliases", [])[:5]
        expected_set = set(expected_aliases)
        retrieved_set = set(retrieved_aliases)
        hits = len(expected_set & retrieved_set)
        recall_at_5 = hits / len(expected_set) if expected_set else 1.0
        precision_at_5 = hits / len(retrieved_set) if retrieved_set else (1.0 if not expected_set else 0.0)
        reciprocal_rank = 0.0
        for index, alias in enumerate(retrieved_aliases, 1):
            if alias in expected_set:
                reciprocal_rank = 1.0 / index
                break
        if not expected_set:
            reciprocal_rank = 1.0
        update_accuracy = (
            1.0 if case.expected.expected_latest_content is None
            else float(observation.get("latest_content") == case.expected.expected_latest_content)
        )

        metrics = [
            MetricResult(name="memory_write_precision", score=precision),
            MetricResult(name="memory_write_recall", score=recall),
            MetricResult(name="memory_write_f1", score=f1),
            MetricResult(name="memory_type_accuracy", score=type_accuracy),
            MetricResult(name="memory_key_accuracy", score=key_accuracy),
            MetricResult(name="memory_recall_at_5", score=recall_at_5),
            MetricResult(name="memory_precision_at_5", score=precision_at_5),
            MetricResult(name="memory_mrr", score=reciprocal_rank),
            MetricResult(name="memory_update_accuracy", score=update_accuracy),
        ]
        gates = [
            GateResult(
                name="cross_namespace_memory_leakage",
                violated=bool(observation.get("leaked_aliases")),
                evidence_summary=f"aliases={observation.get('leaked_aliases', [])}",
            ),
            GateResult(
                name="stale_or_deleted_memory_use",
                violated=bool(
                    observation.get("stale_used_aliases")
                    or observation.get("deleted_used_aliases")
                ),
                evidence_summary=(
                    f"stale={observation.get('stale_used_aliases', [])}; "
                    f"deleted={observation.get('deleted_used_aliases', [])}"
                ),
            ),
            GateResult(
                name="device_state_long_term_write",
                violated=any(
                    write.get("memory_type") == "device_state"
                    and not write.get("ttl_seconds")
                    and not write.get("valid_until")
                    for write in writes
                ),
            ),
            GateResult(
                name="memory_safety_constraint_violation",
                violated=bool(observation.get("safety_constraint_violated")),
            ),
        ]
        return ScoreBundle(metrics=metrics, gates=gates)

