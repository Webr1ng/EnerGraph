"""test_document_knowledge — 上传文件 RAG 的生命周期、检索和路由回归

所属层：tests
依赖：pytest, langchain_core, src.services.document_knowledge
对接算法层：N/A（Mock ChromaDB）
"""
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from src.graph.nodes import _enforce_hvac_tool_route
from src.services.document_knowledge import DocumentKnowledgeService, DocumentProcessingError
from src.skills.document_knowledge_skill import DocumentKnowledgeSkill
from src.tools import TOOL_REGISTRY


class FakeCollection:
    """仅实现文档服务所需 Chroma collection 契约的内存替身。"""

    def __init__(self) -> None:
        self.items: dict[str, tuple[str, dict]] = {}

    def upsert(self, ids, documents, metadatas) -> None:
        for identifier, document, metadata in zip(ids, documents, metadatas):
            self.items[identifier] = (document, metadata)

    def delete(self, where) -> None:
        self.items = {
            identifier: item
            for identifier, item in self.items.items()
            if item[1].get("document_id") != where.get("document_id")
        }

    def count(self) -> int:
        return len(self.items)

    def query(self, query_texts, n_results, include) -> dict:
        selected = list(self.items.values())[:n_results]
        return {
            "documents": [[item[0] for item in selected]],
            "distances": [[0.2 for _ in selected]],
            "metadatas": [[item[1] for item in selected]],
        }


@pytest.fixture
def service(tmp_path: Path, monkeypatch) -> DocumentKnowledgeService:
    """创建不依赖本地 embedding 或真实 Chroma 的文档服务。"""
    instance = DocumentKnowledgeService(storage_dir=tmp_path / "uploads")
    collection = FakeCollection()
    monkeypatch.setattr(instance, "_get_collection", lambda create: collection)
    return instance


def test_txt_upload_recall_duplicate_and_delete(service: DocumentKnowledgeService) -> None:
    """TXT 入库后应可引用召回；重复上传复用；删除后不能再检索。"""
    result = service.upload_bytes("运行手册.txt", "冷水机组应每月检查冷却水温度。".encode())

    assert result.document.status.value == "ready"
    assert result.document.chunk_count == 1
    recalled = service.search("冷却水温度怎么检查")
    assert recalled.low_confidence is False
    assert recalled.sources[0].file_name == "运行手册.txt"

    duplicate = service.upload_bytes("副本.txt", "冷水机组应每月检查冷却水温度。".encode())
    assert duplicate.duplicate is True
    assert duplicate.document.document_id == result.document.document_id

    assert service.delete_document(result.document.document_id) is True
    assert service.search("冷却水温度怎么检查").low_confidence is True


def test_json_upload_keeps_field_content(service: DocumentKnowledgeService) -> None:
    """JSON 应被展开成可检索字段路径和值。"""
    result = service.upload_bytes(
        "设备.json", '{"device":{"name":"冷水机","interval":"每月"}}'.encode()
    )

    assert result.document.status.value == "ready"
    recalled = service.search("设备检查周期")
    assert "device.name: 冷水机" in recalled.results[0]


@pytest.mark.parametrize("suffix", [".doc", ".docx", ".pdf"])
def test_supported_binary_formats_enter_parse_pipeline(
    service: DocumentKnowledgeService, monkeypatch, suffix: str
) -> None:
    """DOC/DOCX/PDF 均应进入统一解析、切块、入库主流程。"""
    captured: list[str] = []

    def parse_file(_path: Path, file_type: str):
        captured.append(file_type)
        return [("测试章节", 2 if suffix == ".pdf" else None, "测试文档正文")]

    monkeypatch.setattr(service, "_parse_file", parse_file)
    result = service.upload_bytes(f"资料{suffix}", b"not-a-real-document")

    assert result.document.status.value == "ready"
    assert captured == [suffix.lstrip(".")]


def test_empty_unsupported_and_scanned_pdf_failure(service: DocumentKnowledgeService, monkeypatch) -> None:
    """空文件、不支持格式和无法抽取文字的 PDF 必须有确定结果。"""
    with pytest.raises(DocumentProcessingError, match="文件为空"):
        service.upload_bytes("空.txt", b"")
    with pytest.raises(DocumentProcessingError, match="不支持"):
        service.upload_bytes("表格.xlsx", b"data")

    monkeypatch.setattr(
        service,
        "_parse_file",
        lambda _path, _kind: (_ for _ in ()).throw(
            DocumentProcessingError("PDF 未提取到文字，扫描件 OCR 将在后续版本支持")
        ),
    )
    result = service.upload_bytes("扫描件.pdf", b"pdf")
    assert result.document.status.value == "failed"
    assert "OCR" in (result.document.failure_reason or "")


def test_reprocess_updates_retry_count(service: DocumentKnowledgeService, monkeypatch) -> None:
    """重新解析必须从原文件执行并累加重试次数。"""
    monkeypatch.setattr(service, "_parse_file", lambda *_args: [("正文", None, "初始内容")])
    uploaded = service.upload_bytes("重试.txt", b"content")
    monkeypatch.setattr(service, "_parse_file", lambda *_args: [("正文", None, "重新解析内容")])

    result = service.reprocess(uploaded.document.document_id)
    assert result.document.status.value == "ready"
    assert result.document.retry_count == 1
    assert "重新解析内容" in service.search("测试").results[0]


def test_document_route_is_forced_without_llm_tool_call() -> None:
    """明确依据上传资料提问时，本地模型漏调 Tool 也必须补上文档 RAG。"""
    response = AIMessage(content="我来回答")
    routed = _enforce_hvac_tool_route(
        response,
        "根据我上传的运维手册，冷水机怎么维护？",
        {"user_input": "根据我上传的运维手册，冷水机怎么维护？"},
    )

    assert "query_uploaded_documents" in [call["name"] for call in routed.tool_calls]
    assert "query_uploaded_documents" in TOOL_REGISTRY


def test_document_skill_refuses_low_confidence_and_formats_source(monkeypatch) -> None:
    """文档 Skill 必须在低置信度拒答，并为命中结果注入文件级引用。"""
    monkeypatch.setattr(
        "src.skills.document_knowledge_skill.load_prompts",
        lambda: {
            "document_knowledge_refusal": {"system": "未在知识库找到可靠内容"},
            "document_knowledge_citation_format": {"system": "必须列出文件页码"},
        },
    )
    skill = DocumentKnowledgeSkill()
    refused = skill.execute(
        [("query_uploaded_documents", {"query": "问题", "low_confidence": True}, {})], {}
    )
    assert refused["document_context_hint"]["low_confidence"] is True
    assert "未在知识库" in refused["document_context_hint"]["system_suffix"]

    cited = skill.execute(
        [("query_uploaded_documents", {
            "query": "问题", "low_confidence": False, "results": ["片段"],
            "sources": [{"file_name": "手册.pdf", "page": 3, "section": "维护"}],
        }, {})], {}
    )
    assert "手册.pdf，第 3 页，维护" in cited["document_context_hint"]["system_suffix"]
