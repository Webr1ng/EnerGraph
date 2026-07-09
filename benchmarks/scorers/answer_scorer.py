"""answer_scorer — 多意图执行完整性与最终回答规则评分

所属层：tests
依赖：benchmarks.scorers.base
对接算法层：N/A
"""
import re

from benchmarks.adapters.base import AdapterResponse
from benchmarks.scorers.base import BaseScorer, ScoreBundle
from benchmarks.shared.result_models import EvalCase, GateResult, MetricResult


class AnswerScorer(BaseScorer):
    """评估意图覆盖、执行顺序、分段和确定性回答质量。"""

    name = "answer_quality"

    def score(self, case: EvalCase, response: AdapterResponse) -> ScoreBundle:
        """生成五项指标和四类 gate。"""
        spec = case.fixtures.get("answer_expected", {})
        observation = response.observations.get("answer_quality", {})
        expected_intents = spec.get("intents", [])
        executed = observation.get("executed_intents", [])
        coverage = (
            len(set(expected_intents).intersection(executed)) / len(set(expected_intents))
            if expected_intents else 1.0
        )
        completeness = float(all(intent in executed for intent in expected_intents))
        expected_order = spec.get("execution_order", [])
        actual_order = observation.get("execution_order", [])
        filtered_order = [intent for intent in actual_order if intent in expected_order]
        order_accuracy = float(not expected_order or filtered_order == expected_order)

        sections = spec.get("sections", [])
        section_score = (
            sum(section in response.answer for section in sections) / len(sections)
            if sections else 1.0
        )
        required_text = spec.get("required_text", [])
        required_any_text = spec.get("required_any_text", [])
        forbidden_text = spec.get("forbidden_text", [])
        normalized_answer = re.sub(r"\s+", "", response.answer).casefold()

        def contains_text(text: str) -> bool:
            """忽略大小写和排版空白检查确定性文本。"""
            return re.sub(r"\s+", "", text).casefold() in normalized_answer

        quality_checks = [contains_text(text) for text in required_text]
        quality_checks.extend(
            any(contains_text(alternative) for alternative in alternatives)
            for alternatives in required_any_text
        )
        quality_checks.extend(not contains_text(text) for text in forbidden_text)
        deterministic_quality = (
            sum(quality_checks) / len(quality_checks) if quality_checks else 1.0
        )
        missing_intents = [intent for intent in expected_intents if intent not in executed]
        forbidden_hits = [text for text in forbidden_text if contains_text(text)]

        return ScoreBundle(
            metrics=[
                MetricResult(name="intent_coverage", score=coverage),
                MetricResult(name="execution_completeness", score=completeness),
                MetricResult(name="dependency_order_accuracy", score=order_accuracy),
                MetricResult(name="section_coverage", score=section_score),
                MetricResult(name="deterministic_answer_quality", score=deterministic_quality),
            ],
            gates=[
                GateResult(
                    name="missing_intent_execution", violated=bool(missing_intents),
                    evidence_summary=f"missing={missing_intents}",
                ),
                GateResult(name="dependency_order_violation", violated=order_accuracy < 1.0),
                GateResult(name="missing_report_section", violated=section_score < 1.0),
                GateResult(
                    name="forbidden_answer_behavior", violated=bool(forbidden_hits),
                    evidence_summary=f"texts={forbidden_hits}",
                ),
            ],
        )
