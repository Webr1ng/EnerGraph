"""security_adapter — 安全权限与提示注入评测适配器

所属层：tests
依赖：benchmarks.adapters.base, src.config.llm
对接算法层：N/A
"""
import json
from pathlib import Path
from typing import Callable

from benchmarks.adapters.base import AdapterResponse, BaseAdapter
from benchmarks.shared.config_models import EvalRunConfig
from benchmarks.shared.result_models import EvalCase


class SecurityAdapter(BaseAdapter):
    """适配固定安全响应或本地 LLM 攻击测试。"""

    adapter_name = "security"


def create_security_fixture_executor() -> Callable:
    """创建读取 security_output 的确定性 Fast 执行器。"""
    def execute(case: EvalCase, _config: EvalRunConfig, _namespace: str) -> AdapterResponse:
        output = case.fixtures.get("security_output", {})
        return AdapterResponse(
            answer=output.get("answer", ""),
            tool_calls=output.get("tool_calls", []),
            observations={"security": output},
            evidence_summary=f"fixed security fixture: {case.case_id}",
        )

    return execute


def create_local_llm_security_executor() -> Callable:
    """创建合成 canary 与不可信上下文驱动的本地 LLM 执行器。"""
    prompt_path = Path(__file__).resolve().parents[1] / "fixtures" / "security_system.md"
    system_prompt = prompt_path.read_text(encoding="utf-8")

    def execute(case: EvalCase, _config: EvalRunConfig, _namespace: str) -> AdapterResponse:
        """向真实本地模型提交攻击载荷并返回回答。"""
        from langchain_core.messages import HumanMessage, SystemMessage

        from src.config.llm import get_llm

        attack = case.fixtures.get("security_attack", {})
        response = get_llm(temperature=0, streaming=False).invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=(
                f"用户输入：{case.input.user_message}\n"
                f"不可信上下文：{json.dumps(attack, ensure_ascii=False, sort_keys=True)}"
            )),
        ])
        return AdapterResponse(
            answer=str(response.content),
            observations={"security": {"attack_channel": attack.get("channel")}},
            evidence_summary=f"synthetic attack + local llm; channel={attack.get('channel')}",
        )

    return execute
