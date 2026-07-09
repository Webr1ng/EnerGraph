"""faithfulness_scorer — 数值、单位、站点、拒答与 DataCard 忠实度评分

所属层：tests
依赖：benchmarks.scorers.base
对接算法层：N/A
"""
import re
from typing import Any

from benchmarks.adapters.base import AdapterResponse
from benchmarks.scorers.base import BaseScorer, ScoreBundle
from benchmarks.shared.result_models import EvalCase, GateResult, MetricResult


_NUMERIC_CLAIM = re.compile(
    r"(?P<value>-?\d+(?:\.\d+)?)\s*(?P<unit>kWh|MWh|kW|MW|kgCO2|tCO2|%|元)"
)


def _numeric_claims(answer: str) -> list[tuple[float, str]]:
    """抽取回答中带业务单位的数值声明，日期和编号不计入。"""
    return [(float(match.group("value")), match.group("unit")) for match in _NUMERIC_CLAIM.finditer(answer)]


def _claim_matches(actual: tuple[float, str], evidence: dict[str, Any]) -> bool:
    """按单位和显式容差比较回答声明与证据。"""
    value, unit = actual
    tolerance = float(evidence.get("tolerance", 0.005))
    return unit == evidence["unit"] and abs(value - float(evidence["value"])) <= tolerance


class FaithfulnessScorer(BaseScorer):
    """评估证据支持率、数值忠实度、正确拒答与 DataCard 一致性。"""

    name = "faithfulness"

    def score(self, case: EvalCase, response: AdapterResponse) -> ScoreBundle:
        """生成四项指标和四类 P0 硬门禁。"""
        spec = case.fixtures.get("faithfulness_expected", {})
        output = response.observations.get("faithfulness", {})
        answer = response.answer
        evidence_claims = spec.get("numeric_claims", [])
        actual_claims = _numeric_claims(answer)
        matched = [any(_claim_matches(claim, item) for item in evidence_claims) for claim in actual_claims]
        numeric_faithfulness = sum(matched) / len(matched) if matched else 1.0

        required_facts = spec.get("required_facts", [])
        fact_score = (
            sum(fact in answer for fact in required_facts) / len(required_facts)
            if required_facts else 1.0
        )
        supported_claim_rate = (numeric_faithfulness + fact_score) / 2

        should_abstain = bool(spec.get("should_abstain"))
        abstention_markers = spec.get("abstention_markers", ["无法", "暂无", "不能", "请重新"])
        # 部分数据回答可以说明“无法汇总”并仍忠实提供已有数值；只有没有任何
        # 证据数值声明时才视为完整拒答。
        did_abstain = any(marker in answer for marker in abstention_markers) and not actual_claims
        correct_abstention = float(did_abstain if should_abstain else not did_abstain)

        expected_card = spec.get("data_card")
        actual_card = output.get("data_card")
        data_card_consistency = float(expected_card is None or actual_card == expected_card)

        wrong_site = any(site in answer for site in spec.get("forbidden_sites", []))
        wrong_unit = any(
            any(
                abs(claim[0] - float(item["value"])) <= float(item.get("tolerance", 0.005))
                and claim[1] != item["unit"]
                for item in evidence_claims
            )
            for claim in actual_claims
        )
        return ScoreBundle(
            metrics=[
                MetricResult(name="supported_claim_rate", score=supported_claim_rate),
                MetricResult(name="numeric_faithfulness", score=numeric_faithfulness),
                MetricResult(name="correct_abstention", score=correct_abstention),
                MetricResult(name="data_card_consistency", score=data_card_consistency),
            ],
            gates=[
                GateResult(
                    name="unsupported_energy_numeric", violated=any(not item for item in matched),
                    evidence_summary=f"claims={actual_claims}",
                ),
                GateResult(
                    name="wrong_unit_or_site", violated=wrong_unit or wrong_site,
                    evidence_summary=f"wrong_unit={wrong_unit}; wrong_site={wrong_site}",
                ),
                GateResult(
                    name="fabricated_data_card",
                    violated=expected_card is not None and actual_card != expected_card,
                ),
                GateResult(
                    name="missing_required_abstention", violated=should_abstain and not did_abstain,
                ),
            ],
        )
