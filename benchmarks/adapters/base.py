"""base — Eval Adapter 统一响应、重试与 namespace 生命周期

所属层：tests
依赖：abc, pydantic, benchmarks.shared
对接算法层：N/A
"""
from abc import ABC
import signal
import threading
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel, Field

from benchmarks.shared.config_models import EvalRunConfig
from benchmarks.shared.result_models import EvalCase, ToolCallRecord


class AdapterResponse(BaseModel):
    """Adapter 向后续 Scorer 暴露的实现无关响应。"""

    actual_intents: List[str] = Field(default_factory=list)
    actual_agent: Optional[str] = None
    actual_skill: Optional[str] = None
    tool_calls: List[ToolCallRecord] = Field(default_factory=list)
    answer: str = ""
    protocol_events: List[Dict[str, Any]] = Field(default_factory=list)
    input_tokens: Optional[int] = Field(default=None, ge=0)
    output_tokens: Optional[int] = Field(default=None, ge=0)
    error: Optional[str] = None
    evidence_summary: Optional[str] = None
    observations: Dict[str, Any] = Field(default_factory=dict)


AdapterExecutor = Callable[[EvalCase, EvalRunConfig, str], AdapterResponse]
NamespaceCleaner = Callable[[str], None]


class AdapterTimeoutError(TimeoutError):
    """Adapter 单次执行超过配置预算。"""


class BaseAdapter(ABC):
    """统一处理案例隔离、清理与有限重试的 Adapter 基类。"""

    adapter_name = "base"

    def __init__(
        self,
        config: EvalRunConfig,
        executor: AdapterExecutor,
        namespace_cleaner: Optional[NamespaceCleaner] = None,
    ) -> None:
        """注入运行配置、具体执行器与可选 namespace 清理器。"""
        self.config = config
        self.executor = executor
        self.namespace_cleaner = namespace_cleaner

    def case_namespace(self, case: EvalCase) -> str:
        """生成仅属于当前模式和案例的确定性 namespace。"""
        return f"{self.config.options.namespace_prefix}/{self.adapter_name}/{case.case_id}"

    def run(self, case: EvalCase) -> AdapterResponse:
        """清理 namespace 后执行案例，并在成功或失败后再次清理。"""
        namespace = self.case_namespace(case)
        if self.namespace_cleaner:
            self.namespace_cleaner(namespace)
        try:
            attempts = self.config.options.retries + 1
            for attempt in range(attempts):
                try:
                    response = self._execute_with_timeout(case, namespace)
                    return AdapterResponse.model_validate(response)
                except Exception:
                    if attempt == attempts - 1:
                        raise
            raise RuntimeError("Adapter 重试循环异常结束")
        finally:
            if self.namespace_cleaner:
                self.namespace_cleaner(namespace)

    def _execute_with_timeout(self, case: EvalCase, namespace: str) -> AdapterResponse:
        """在主线程使用系统定时器强制执行单次超时预算。"""
        timeout = self.config.options.timeout_seconds
        if threading.current_thread() is not threading.main_thread() or not hasattr(signal, "SIGALRM"):
            return self.executor(case, self.config, namespace)

        def raise_timeout(_signum, _frame) -> None:
            raise AdapterTimeoutError(
                f"{self.adapter_name} adapter 超时: {timeout:g}s, case_id={case.case_id}"
            )

        previous_handler = signal.getsignal(signal.SIGALRM)
        signal.signal(signal.SIGALRM, raise_timeout)
        previous_timer = signal.setitimer(signal.ITIMER_REAL, timeout)
        try:
            return self.executor(case, self.config, namespace)
        finally:
            signal.setitimer(signal.ITIMER_REAL, *previous_timer)
            signal.signal(signal.SIGALRM, previous_handler)
