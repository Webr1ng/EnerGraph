"""answer_adapter — 多意图执行与最终回答质量评测适配器

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


class AnswerAdapter(BaseAdapter):
    """适配固定多意图结果或本地 LLM 报告生成。"""

    adapter_name = "answer"


def create_answer_fixture_executor() -> Callable:
    """创建读取 answer_output 的确定性 Fast 执行器。"""
    def execute(case: EvalCase, _config: EvalRunConfig, _namespace: str) -> AdapterResponse:
        output = case.fixtures.get("answer_output", {})
        return AdapterResponse(
            answer=output.get("answer", ""),
            observations={"answer_quality": output},
            evidence_summary=f"fixed answer fixture: {case.case_id}",
        )

    return execute


def create_local_llm_answer_executor() -> Callable:
    """创建固定执行证据驱动的本地 LLM 分段报告执行器。"""
    prompt_path = Path(__file__).resolve().parents[1] / "fixtures" / "answer_system.md"
    system_prompt = prompt_path.read_text(encoding="utf-8")

    def execute(case: EvalCase, _config: EvalRunConfig, _namespace: str) -> AdapterResponse:
        """向本地模型提供已执行意图与证据，返回最终报告。"""
        from langchain_core.messages import HumanMessage, SystemMessage

        from src.config.llm import get_llm

        expected = case.fixtures.get("answer_expected", {})
        output = case.fixtures.get("answer_output", {})
        evidence = {
            "intents": expected.get("intents", []),
            "execution_order": expected.get("execution_order", []),
            "sections": expected.get("sections", []),
            "facts": output.get("evidence_facts", []),
            "failed_intents": output.get("failed_intents", []),
        }
        llm = get_llm(temperature=0, streaming=False)
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=(
                f"用户请求：{case.input.user_message}\n"
                f"执行证据：{json.dumps(evidence, ensure_ascii=False, sort_keys=True)}\n"
                f"必须逐字输出的分段标题：{json.dumps(expected.get('sections', []), ensure_ascii=False)}"
            )),
        ]
        response = llm.invoke(messages)
        answer = str(response.content)
        missing_sections = [
            section for section in expected.get("sections", []) if section not in answer
        ]
        if missing_sections:
            response = llm.invoke(messages + [
                HumanMessage(content=(
                    "上一版报告未满足格式契约。请重新输出完整报告，不要解释修改过程；"
                    f"以下标题必须逐字出现且各出现一次：{json.dumps(expected.get('sections', []), ensure_ascii=False)}"
                )),
            ])
            answer = str(response.content)
        return AdapterResponse(
            answer=answer,
            observations={"answer_quality": {
                "executed_intents": output.get("executed_intents", []),
                "execution_order": output.get("execution_order", []),
            }},
            evidence_summary="fixed execution evidence + local llm",
        )

    return execute
