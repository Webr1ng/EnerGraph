"""api_adapter — HTTP/SSE API 的 Eval Adapter 边界

所属层：tests
依赖：benchmarks.adapters.base
对接算法层：N/A
"""
from benchmarks.adapters.base import AdapterResponse, BaseAdapter
from benchmarks.shared.result_models import EvalCase


class ApiAdapter(BaseAdapter):
    """适配 HTTP/SSE 传输，并严格阻止 Fast 模式网络访问。"""

    adapter_name = "api"

    def run(self, case: EvalCase) -> AdapterResponse:
        """在允许网络的模式下调用注入的 API transport。"""
        if not self.config.network_allowed:
            raise RuntimeError("当前模式禁止 API 网络访问")
        return super().run(case)

