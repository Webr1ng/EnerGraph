"""v0_1 — 数据忠实度 MiniBench v0.1 入口

所属层：tests
依赖：benchmarks.datasets.faithfulness.v0_1.loader
对接算法层：N/A
"""
from benchmarks.datasets.faithfulness.v0_1.loader import load_faithfulness_cases

__all__ = ["load_faithfulness_cases"]
