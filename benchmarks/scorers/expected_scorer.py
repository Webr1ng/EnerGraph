"""expected_scorer — 最小闭环的通用期望、Tool 与回答评分

所属层：tests
依赖：benchmarks.scorers.base
对接算法层：N/A
"""
from benchmarks.adapters.base import AdapterResponse
from benchmarks.scorers.base import BaseScorer, ScoreBundle
from benchmarks.shared.result_models import EvalCase, GateResult, MetricResult


def _set_f1(expected: set[str], actual: set[str]) -> float:
    """计算集合 F1，双方均为空时定义为 1。"""
    if not expected and not actual:
        return 1.0
    if not expected or not actual:
        return 0.0
    true_positive = len(expected & actual)
    precision = true_positive / len(actual)
    recall = true_positive / len(expected)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


class ExpectedBehaviorScorer(BaseScorer):
    """依据 EvalExpected 生成通用确定性指标与硬门禁。"""

    name = "expected_behavior"

    def score(self, case: EvalCase, response: AdapterResponse) -> ScoreBundle:
        """评分回答包含项、路由、Tool 集合与禁止行为。"""
        expected = case.expected
        actual_tools = {call.name for call in response.tool_calls}
        required_tools = set(expected.required_tools)
        forbidden_tools = set(expected.forbidden_tools)
        missing_contains = [text for text in expected.answer_contains if text not in response.answer]
        hit_forbidden_answer = [text for text in expected.answer_forbidden if text in response.answer]
        hit_forbidden_tools = sorted(actual_tools & forbidden_tools)

        contains_score = (
            1.0 if not expected.answer_contains
            else (len(expected.answer_contains) - len(missing_contains)) / len(expected.answer_contains)
        )
        agent_score = 1.0 if expected.agent is None or response.actual_agent == expected.agent else 0.0
        skill_score = 1.0 if expected.skill is None or response.actual_skill == expected.skill else 0.0
        tool_f1 = _set_f1(required_tools, actual_tools - set(expected.optional_tools))

        return ScoreBundle(
            metrics=[
                MetricResult(
                    name="answer_contains_rate", score=contains_score, threshold=1.0,
                    passed=contains_score == 1.0,
                    evidence_summary=f"missing={missing_contains}",
                ),
                MetricResult(
                    name="agent_accuracy", score=agent_score, threshold=1.0,
                    passed=agent_score == 1.0,
                ),
                MetricResult(
                    name="skill_accuracy", score=skill_score, threshold=1.0,
                    passed=skill_score == 1.0,
                ),
                MetricResult(
                    name="tool_call_f1", score=tool_f1, threshold=1.0,
                    passed=tool_f1 == 1.0,
                ),
            ],
            gates=[
                GateResult(
                    name="adapter_error", violated=bool(response.error),
                    evidence_summary=response.error,
                ),
                GateResult(
                    name="forbidden_tool_call", violated=bool(hit_forbidden_tools),
                    evidence_summary=f"tools={hit_forbidden_tools}",
                ),
                GateResult(
                    name="forbidden_answer_text", violated=bool(hit_forbidden_answer),
                    evidence_summary=f"texts={hit_forbidden_answer}",
                ),
            ],
        )

