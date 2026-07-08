"""v0_1 — Memory MiniBench v0.1 数据集入口

所属层：tests
依赖：benchmarks.datasets.memory.v0_1.loader
对接算法层：N/A
"""

from benchmarks.datasets.memory.v0_1.loader import load_memory_cases

__all__ = ["load_memory_cases"]
