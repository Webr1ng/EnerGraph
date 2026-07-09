"""rag_adapter — RAG 检索层的 Eval Adapter 边界

所属层：tests
依赖：benchmarks.adapters.base, benchmarks.shared
对接算法层：N/A
"""
import json
import re
from pathlib import Path
from typing import Callable

from benchmarks.adapters.base import AdapterResponse, BaseAdapter
from benchmarks.shared.config_models import EvalRunConfig
from benchmarks.shared.result_models import EvalCase


class RagAdapter(BaseAdapter):
    """适配固定语料或真实本地索引检索执行器。"""

    adapter_name = "rag"


def create_rag_fixture_executor() -> Callable:
    """创建读取 rag_output 的确定性 Fast 执行器。"""
    def execute(case: EvalCase, _config: EvalRunConfig, _namespace: str) -> AdapterResponse:
        output = case.fixtures.get("rag_output", {})
        return AdapterResponse(
            answer=output.get("answer", ""),
            observations={"rag": output},
            evidence_summary=f"fixed rag fixture: {case.case_id}",
        )

    return execute


def create_local_rag_executor() -> Callable:
    """创建真实本地 Chroma 检索与本地 LLM 回答执行器。"""
    prompt_path = Path(__file__).resolve().parents[1] / "fixtures" / "rag_answer_system.md"
    system_prompt = prompt_path.read_text(encoding="utf-8")

    def execute(case: EvalCase, _config: EvalRunConfig, _namespace: str) -> AdapterResponse:
        """执行真实索引检索，映射文档 ID，并让本地模型基于证据回答。"""
        import chromadb
        from langchain_core.messages import HumanMessage, SystemMessage

        from src.config.llm import get_llm
        from src.tools.query_hvac_knowledge import (
            COLLECTION_NAME,
            DB_PATH,
            query_hvac_knowledge,
        )

        result = query_hvac_knowledge(case.input.user_message)
        if result.get("error"):
            index_missing = "知识库尚未初始化" in result["error"]
            return AdapterResponse(
                error=None if index_missing else result["error"],
                observations={"rag": {"index_missing": index_missing}},
                evidence_summary=result["error"],
            )

        collection = chromadb.PersistentClient(path=DB_PATH).get_collection(COLLECTION_NAME)
        snapshot = collection.get(include=["documents"])
        ids_by_document = {
            document: doc_id for doc_id, document in zip(snapshot["ids"], snapshot["documents"])
        }
        documents = result.get("results", [])
        retrieved_ids = [ids_by_document.get(document, "unknown") for document in documents]
        low_confidence = bool(result.get("low_confidence"))
        evidence = [
            {"doc_id": doc_id, "content": document[:1200]}
            for doc_id, document in zip(retrieved_ids[:3], documents[:3])
        ]
        response = get_llm(temperature=0, streaming=False).invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=(
                f"用户问题：{case.input.user_message}\n"
                f"low_confidence={str(low_confidence).lower()}\n"
                f"检索片段：{json.dumps(evidence, ensure_ascii=False)}"
            )),
        ])
        answer = str(response.content)
        citations = list(dict.fromkeys(re.findall(r"hvac_\d+|supplement_\d+", answer)))
        return AdapterResponse(
            answer=answer,
            observations={"rag": {
                "retrieved_ids": retrieved_ids,
                "retrieved_documents": documents,
                "citations": citations,
                "low_confidence": low_confidence,
                "index_snapshot_count": len(snapshot["ids"]),
            }},
            evidence_summary=(
                f"local chroma count={len(snapshot['ids'])}; low_confidence={low_confidence}"
            ),
        )

    return execute
