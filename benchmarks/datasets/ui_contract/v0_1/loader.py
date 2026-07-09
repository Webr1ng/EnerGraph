"""loader — 将 10 个前端契约基础场景扩展为 30 条记录

所属层：tests
依赖：benchmarks.shared.case_loader
对接算法层：N/A
"""
from pathlib import Path
from typing import List

from benchmarks.shared.case_loader import load_cases
from benchmarks.shared.result_models import EvalCase


def load_ui_contract_cases(path: Path | str | None = None) -> List[EvalCase]:
    """加载基础场景，并按每场景三种请求扩展为 30 records。"""
    source = Path(path) if path else Path(__file__).with_name("base_cases.jsonl")
    expanded: List[EvalCase] = []
    for case in load_cases(source):
        utterances = case.fixtures.get("utterances", [])
        if len(utterances) != 3:
            raise ValueError(f"{case.case_id}: utterances 必须恰好 3 条")
        for index, utterance in enumerate(utterances, 1):
            clone = case.model_copy(deep=True)
            clone.case_id = f"{case.case_id}_v{index:02d}"
            clone.input.user_message = utterance
            clone.input.thread_id = f"{case.input.thread_id}_v{index:02d}"
            expanded.append(clone)
    return expanded
