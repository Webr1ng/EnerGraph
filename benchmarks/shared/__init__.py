"""shared — EnerGraph Eval 共用契约、加载与报告基础设施。"""

from benchmarks.shared.case_loader import load_cases
from benchmarks.shared.result_models import EvalCase, EvalResult, RunManifest

__all__ = ["EvalCase", "EvalResult", "RunManifest", "load_cases"]
