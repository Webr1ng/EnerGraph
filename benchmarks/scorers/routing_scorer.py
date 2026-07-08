"""routing_scorer — 意图、Agent、Skill 与 Top-k 路由评分

所属层：tests
依赖：benchmarks.scorers.base
对接算法层：N/A
"""
from benchmarks.adapters.base import AdapterResponse
from benchmarks.scorers.base import BaseScorer, ScoreBundle
from benchmarks.shared.result_models import EvalCase, MetricResult


def _set_f1(expected: set[str], actual: set[str]) -> float:
    """计算多标签 intent F1。"""
    if not expected and not actual:
        return 1.0
    if not expected or not actual:
        return 0.0
    hits = len(expected & actual)
    precision = hits / len(actual)
    recall = hits / len(expected)
    return 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)


class RoutingScorer(BaseScorer):
    """确定性评估单/多意图和 Agent/Skill 路由。"""

    name = "routing"

    def score(self, case: EvalCase, response: AdapterResponse) -> ScoreBundle:
        """生成 intent accuracy、Macro-F1 代理、Top-k 与路由准确率。"""
        expected = set(case.expected.intents)
        actual = set(response.actual_intents)
        intent_accuracy = float(expected == actual)
        intent_f1 = _set_f1(expected, actual)
        top_intents = response.observations.get("routing", {}).get(
            "top_intents", response.actual_intents
        )
        top_k_accuracy = float(not expected or expected.issubset(set(top_intents[:3])))
        agent_accuracy = float(
            case.expected.agent is None or response.actual_agent == case.expected.agent
        )
        skill_accuracy = float(
            case.expected.skill is None or response.actual_skill == case.expected.skill
        )
        return ScoreBundle(metrics=[
            MetricResult(name="intent_accuracy", score=intent_accuracy),
            MetricResult(name="intent_macro_f1", score=intent_f1),
            MetricResult(name="intent_top3_accuracy", score=top_k_accuracy),
            MetricResult(name="agent_routing_accuracy", score=agent_accuracy),
            MetricResult(name="skill_routing_accuracy", score=skill_accuracy),
        ])

