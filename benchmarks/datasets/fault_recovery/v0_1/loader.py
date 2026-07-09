"""loader — 加载 PostgreSQL 与外部服务故障恢复验收案例

所属层：tests
依赖：benchmarks.shared.case_loader
对接算法层：N/A
"""
from pathlib import Path
from typing import List

from benchmarks.shared.case_loader import load_cases
from benchmarks.shared.result_models import EvalCase


def load_fault_recovery_cases(path: Path | str | None = None) -> List[EvalCase]:
    """加载 T14 故障恢复基础案例。"""
    source = Path(path) if path else Path(__file__).with_name("base_cases.jsonl")
    return load_cases(source)
