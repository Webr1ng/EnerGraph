"""repository — 固定 Fixture 响应加载与案例查找

所属层：tests
依赖：json, benchmarks.adapters.base
对接算法层：N/A
"""
import json
from pathlib import Path
from typing import Any, Dict

from benchmarks.adapters.base import AdapterResponse
from benchmarks.shared.result_models import EvalCase


class FixtureRepository:
    """按 case_id 提供固定 Adapter 响应。"""

    def __init__(self, responses: Dict[str, Dict[str, Any]]) -> None:
        """初始化 Fixture 仓库。"""
        self._responses = responses

    @classmethod
    def from_json(cls, path: Path | str) -> "FixtureRepository":
        """从 JSON 对象加载固定响应。"""
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Fixture 根节点必须是 case_id 到响应的对象")
        return cls(payload)

    def execute(self, case: EvalCase, *_: Any) -> AdapterResponse:
        """返回指定案例的固定响应，不访问网络。"""
        if case.case_id not in self._responses:
            raise KeyError(f"Fixture 缺少 case_id: {case.case_id}")
        return AdapterResponse.model_validate(self._responses[case.case_id])

