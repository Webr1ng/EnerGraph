"""v0_1 — Tool Call MiniBench v0.1 入口

所属层：tests
依赖：benchmarks.datasets.tool_call.v0_1.loader
对接算法层：N/A
"""

from benchmarks.datasets.tool_call.v0_1.loader import load_tool_call_cases

__all__ = ["load_tool_call_cases"]
