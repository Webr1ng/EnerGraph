"""base — Scorer 统一结果与注册执行框架

所属层：tests
依赖：abc, pydantic, benchmarks.shared
对接算法层：N/A
"""
from abc import ABC, abstractmethod
from typing import Dict, Iterable, List

from pydantic import BaseModel, Field

from benchmarks.adapters.base import AdapterResponse
from benchmarks.shared.result_models import EvalCase, GateResult, MetricResult


class ScoreBundle(BaseModel):
    """单个 Scorer 产生的指标与门禁集合。"""

    metrics: List[MetricResult] = Field(default_factory=list)
    gates: List[GateResult] = Field(default_factory=list)


class BaseScorer(ABC):
    """Scorer 抽象接口。"""

    name = "base"

    @abstractmethod
    def score(self, case: EvalCase, response: AdapterResponse) -> ScoreBundle:
        """对单案例响应评分。"""


class ScorerRegistry:
    """按唯一名称注册并顺序执行 Scorer。"""

    def __init__(self, scorers: Iterable[BaseScorer] = ()) -> None:
        """初始化注册表并注册给定 Scorer。"""
        self._scorers: Dict[str, BaseScorer] = {}
        for scorer in scorers:
            self.register(scorer)

    def register(self, scorer: BaseScorer) -> None:
        """注册 Scorer，拒绝名称重复。"""
        if scorer.name in self._scorers:
            raise ValueError(f"Scorer 名称重复: {scorer.name}")
        self._scorers[scorer.name] = scorer

    def score(self, case: EvalCase, response: AdapterResponse) -> ScoreBundle:
        """执行全部 Scorer 并合并指标与门禁。"""
        combined = ScoreBundle()
        for scorer in self._scorers.values():
            bundle = scorer.score(case, response)
            combined.metrics.extend(bundle.metrics)
            combined.gates.extend(bundle.gates)
        return combined

