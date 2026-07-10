"""query_uploaded_documents — 用户上传文档的 RAG 检索工具

所属层：tools
依赖：src.services.document_knowledge, src.schemas.document_knowledge
对接算法层：N/A（本地 ChromaDB 文档检索）
"""
import logging
from typing import Any, Dict

from src.services.document_knowledge import DocumentKnowledgeService

logger = logging.getLogger(__name__)


def query_uploaded_documents(question: str) -> Dict[str, Any]:
    """检索用户上传文档，并返回可引用的文本片段和来源。

    Args:
        question: 用户关于已上传资料、报告、规范或手册的具体问题。

    Returns:
        DocumentKnowledgeResult 的 dict 表示；异常时返回 error 字段。
    """
    try:
        return DocumentKnowledgeService().search(question).model_dump(mode="json")
    except Exception as exc:
        logger.error("query_uploaded_documents 失败: %s", exc)
        return {"error": f"query_uploaded_documents: {exc}"}
