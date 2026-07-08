"""v0_1 — 安全 MiniBench v0.1 入口

所属层：tests
依赖：benchmarks.datasets.security.v0_1.loader
对接算法层：N/A
"""
from benchmarks.datasets.security.v0_1.loader import load_security_cases

__all__ = ["load_security_cases"]
