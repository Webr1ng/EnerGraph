"""rag_adapter — RAG 检索层的 Eval Adapter 边界

所属层：tests
依赖：benchmarks.adapters.base
对接算法层：N/A
"""
from benchmarks.adapters.base import BaseAdapter


class RagAdapter(BaseAdapter):
    """适配固定语料或真实本地索引检索执行器。"""

    adapter_name = "rag"

