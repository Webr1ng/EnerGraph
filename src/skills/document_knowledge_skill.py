"""document_knowledge_skill — 上传文档检索问答技能

所属层：skills
依赖：src.tools.query_uploaded_documents, src.config.settings
对接算法层：N/A（ChromaDB 文档知识库）
"""
import logging
from typing import Any, Dict, List, Optional, Tuple

from src.skills.base_skill import BaseSkill, load_prompts

logger = logging.getLogger(__name__)


class DocumentKnowledgeSkill(BaseSkill):
    """将上传文档检索结果转为带来源约束的 Agent 上下文。"""

    name = "document_knowledge"
    tools = ["query_uploaded_documents"]
    prompt_keys = ["document_knowledge_refusal", "document_knowledge_citation_format"]
    description = "用户上传资料、报告、规范和手册的检索问答"

    def execute(
        self,
        tool_results: List[Tuple[str, Dict[str, Any], Dict[str, Any]]],
        state: Dict[str, Any],
    ) -> Dict[str, Any]:
        """处理文档检索结果并配置引用或拒答约束。

        Args:
            tool_results: 本轮工具调用的名称、结果和参数。
            state: 当前 AgentState（只读）。

        Returns:
            包含 document_context_hint 的状态更新。
        """
        document_result: Optional[Dict[str, Any]] = next(
            (
                result
                for name, result, _args in tool_results
                if name == "query_uploaded_documents" and "error" not in result
            ),
            None,
        )
        if document_result is None:
            return {
                "document_context_hint": {
                    "system_suffix": "",
                    "context_override": None,
                    "low_confidence": False,
                }
            }

        prompts = load_prompts()
        if document_result.get("low_confidence", True):
            refusal_prompt = prompts.get("document_knowledge_refusal", {}).get("system", "")
            return {
                "document_context_hint": {
                    "system_suffix": f"\n\n{refusal_prompt}",
                    "context_override": {
                        "low_confidence": True,
                        "query": document_result.get("query", ""),
                    },
                    "low_confidence": True,
                }
            }

        citation_prompt = prompts.get("document_knowledge_citation_format", {}).get("system", "")
        sources = document_result.get("sources", [])
        source_lines = []
        for source in sources:
            location = source.get("file_name", "未知文件")
            if source.get("page"):
                location += f"，第 {source['page']} 页"
            if source.get("section"):
                location += f"，{source['section']}"
            source_lines.append(f"- {location}")
        suffix = f"\n\n{citation_prompt}"
        if source_lines:
            suffix += "\n\n可用来源：\n" + "\n".join(source_lines)
        logger.info("上传文档检索命中 %s 条", len(document_result.get("results", [])))
        return {
            "document_context_hint": {
                "system_suffix": suffix,
                "context_override": None,
                "low_confidence": False,
            }
        }
