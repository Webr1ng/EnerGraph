"""rag_scorer — HVAC 检索、引用、拒答与答案支持度评分

所属层：tests
依赖：math, benchmarks.scorers.base
对接算法层：N/A
"""
import math

from benchmarks.adapters.base import AdapterResponse
from benchmarks.scorers.base import BaseScorer, ScoreBundle
from benchmarks.shared.result_models import EvalCase, GateResult, MetricResult


def _ndcg(retrieved: list[str], relevant: set[str], k: int = 5) -> float:
    """计算二元相关性的 nDCG@k。"""
    if not relevant:
        return 1.0
    dcg = sum(
        1.0 / math.log2(index + 2)
        for index, doc_id in enumerate(retrieved[:k]) if doc_id in relevant
    )
    ideal = sum(1.0 / math.log2(index + 2) for index in range(min(len(relevant), k)))
    return dcg / ideal if ideal else 1.0


class RagScorer(BaseScorer):
    """评估 HVAC RAG 检索排序、去重、引用、拒答和支持度。"""

    name = "rag"

    def score(self, case: EvalCase, response: AdapterResponse) -> ScoreBundle:
        """生成七项指标和四类 RAG gate。"""
        spec = case.fixtures.get("rag_expected", {})
        observation = response.observations.get("rag", {})
        relevant = set(spec.get("relevant_ids", []))
        retrieved = observation.get("retrieved_ids", [])[:5]
        hits = relevant.intersection(retrieved)
        recall = len(hits) / len(relevant) if relevant else 1.0
        ranks = [index + 1 for index, doc_id in enumerate(retrieved) if doc_id in relevant]
        mrr = 1.0 / min(ranks) if ranks else (1.0 if not relevant else 0.0)
        ndcg = _ndcg(retrieved, relevant)

        documents = observation.get("retrieved_documents", [])
        dedup_rate = len(set(documents)) / len(documents) if documents else 1.0
        citations = observation.get("citations", [])
        allowed_citations = set(spec.get("allowed_citations", spec.get("relevant_ids", [])))
        citation_precision = (
            sum(citation in allowed_citations for citation in citations) / len(citations)
            if citations else (1.0 if spec.get("should_refuse") else 0.0)
        )

        refusal_markers = spec.get("refusal_markers", ["暂无", "无法", "不足", "未检索到"])
        refused = any(marker in response.answer for marker in refusal_markers)
        should_refuse = bool(spec.get("should_refuse"))
        correct_refusal = float(refused if should_refuse else not refused)
        observed_low_confidence = bool(observation.get("low_confidence"))
        low_confidence_accuracy = float(observed_low_confidence == should_refuse)
        unsupported = bool(observation.get("unsupported_claims"))
        supported_answer = float(not unsupported and (should_refuse or bool(response.answer.strip())))
        index_missing = bool(observation.get("index_missing"))

        return ScoreBundle(
            metrics=[
                MetricResult(name="rag_recall_at_5", score=recall),
                MetricResult(name="rag_mrr", score=mrr),
                MetricResult(name="rag_ndcg_at_5", score=ndcg),
                MetricResult(name="rag_dedup_rate", score=dedup_rate),
                MetricResult(name="citation_precision", score=citation_precision),
                MetricResult(name="rag_correct_refusal", score=correct_refusal),
                MetricResult(name="low_confidence_accuracy", score=low_confidence_accuracy),
                MetricResult(name="rag_supported_answer", score=supported_answer),
            ],
            gates=[
                GateResult(name="rag_index_unavailable", violated=index_missing),
                GateResult(
                    name="answered_low_confidence", violated=should_refuse and not refused,
                ),
                GateResult(
                    name="missed_low_confidence",
                    violated=should_refuse and not observed_low_confidence,
                ),
                GateResult(
                    name="unsupported_rag_answer", violated=unsupported,
                ),
                GateResult(
                    name="too_many_or_invalid_citations",
                    violated=len(citations) > 3 or citation_precision < 1.0,
                ),
            ],
        )
