"""faithfulness_adapter — 数据忠实度固定证据适配器

所属层：tests
依赖：benchmarks.adapters.base
对接算法层：N/A
"""
import json
from pathlib import Path
from typing import Callable

from benchmarks.adapters.base import AdapterResponse, BaseAdapter
from benchmarks.shared.config_models import EvalRunConfig
from benchmarks.shared.result_models import EvalCase


class FaithfulnessAdapter(BaseAdapter):
    """适配固定 Tool/RAG/DataCard 证据与回答。"""

    adapter_name = "faithfulness"


def create_faithfulness_fixture_executor() -> Callable:
    """创建读取 faithfulness_output 的确定性 Fast 执行器。"""
    def execute(case: EvalCase, _config: EvalRunConfig, _namespace: str) -> AdapterResponse:
        output = case.fixtures.get("faithfulness_output", {})
        return AdapterResponse(
            answer=output.get("answer", ""),
            observations={"faithfulness": output},
            evidence_summary=f"fixed faithfulness fixture: {case.case_id}",
        )

    return execute


def create_local_llm_faithfulness_executor() -> Callable:
    """创建固定证据驱动的本地 LLM 回答执行器。"""
    prompt_path = Path(__file__).resolve().parents[1] / "fixtures" / "faithfulness_system.md"
    system_prompt = prompt_path.read_text(encoding="utf-8")

    def execute(case: EvalCase, _config: EvalRunConfig, _namespace: str) -> AdapterResponse:
        """向真实本地模型提供固定证据并返回生成回答。"""
        from langchain_core.messages import HumanMessage, SystemMessage

        from src.config.llm import get_llm

        expected = case.fixtures.get("faithfulness_expected", {})
        status = "ok"
        for candidate in ("empty", "error", "conflict", "stale", "low_confidence"):
            if candidate in case.tags:
                status = candidate
                break
        evidence = {
            "status": status,
            "site_id": case.input.site_id,
            "numeric_claims": expected.get("numeric_claims", []),
            "evidence_facts": expected.get("required_facts", []),
        }
        response = get_llm(temperature=0, streaming=False).invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=(
                f"用户问题：{case.input.user_message}\n"
                f"证据 JSON：{json.dumps(evidence, ensure_ascii=False, sort_keys=True)}"
            )),
        ])
        return AdapterResponse(
            answer=str(response.content),
            observations={"faithfulness": {"evidence_status": status}},
            evidence_summary=f"fixed evidence + local llm; status={status}",
        )

    return execute
