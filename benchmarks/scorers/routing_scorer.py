"""routing_scorer — 意图、Agent、Skill 与 Top-k 路由评分

所属层：tests
依赖：benchmarks.scorers.base
对接算法层：N/A
"""
from benchmarks.adapters.base import AdapterResponse
from benchmarks.scorers.base import BaseScorer, ScoreBundle
from benchmarks.shared.result_models import EvalCase, MetricResult


_CLARIFICATION_SIGNALS = (
    "请明确", "请具体", "请问您", "请提供", "请告诉我", "您想查看哪方面", "请选择",
    "站点 ID", "站点ID", "目标站点", "没有检索到站点信息", "无法确定站点",
    "需要您补充", "补充站点", "补充一下", "数据类型", "时间范围",
)


def _normalize_intents(intents: set[str], answer: str) -> set[str]:
    """将行为明确为澄清的无工具 general 回答归一到 clarification。"""
    if "general" in intents and any(signal in answer for signal in _CLARIFICATION_SIGNALS):
        intents = set(intents)
        intents.discard("general")
        intents.add("clarification")
        return intents
    return intents


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
        actual = _normalize_intents(set(response.actual_intents), response.answer)
        intent_accuracy = float(expected == actual)
        intent_f1 = _set_f1(expected, actual)
        top_intents = response.observations.get("routing", {}).get(
            "top_intents", response.actual_intents
        )
        normalized_top_intents = _normalize_intents(set(top_intents[:3]), response.answer)
        top_k_accuracy = float(not expected or expected.issubset(normalized_top_intents))
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
