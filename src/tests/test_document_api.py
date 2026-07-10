"""test_document_api — 文档知识库 FastAPI 管理接口回归

所属层：tests
依赖：httpx, pytest, src.services.api
对接算法层：N/A（Mock 文档知识库服务）
"""
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from src.schemas.document_knowledge import (
    DocumentRecord,
    DocumentStatus,
    DocumentUploadResult,
)
from src.services.api import app


class FakeDocumentService:
    """管理接口测试用的内存文档服务。"""

    def __init__(self) -> None:
        now = datetime.now(timezone.utc)
        self.record = DocumentRecord(
            document_id="doc-001",
            file_name="手册.txt",
            file_type="txt",
            content_hash="hash",
            file_size=5,
            status=DocumentStatus.READY,
            uploaded_at=now,
            updated_at=now,
            chunk_count=1,
        )
        self.deleted = False

    def upload_bytes(self, file_name: str, content: bytes) -> DocumentUploadResult:
        assert file_name == "手册.txt"
        assert content == b"hello"
        return DocumentUploadResult(document=self.record, message="已入库")

    def list_documents(self):
        return [] if self.deleted else [self.record]

    def get_document(self, document_id: str):
        return self.record if document_id == self.record.document_id and not self.deleted else None

    def reprocess(self, document_id: str) -> DocumentUploadResult:
        assert document_id == self.record.document_id
        return DocumentUploadResult(document=self.record, message="已重新解析")

    def delete_document(self, document_id: str) -> bool:
        if document_id != self.record.document_id or self.deleted:
            return False
        self.deleted = True
        return True


@pytest.mark.asyncio
async def test_document_management_endpoints(monkeypatch) -> None:
    """上传、列表、详情、重解析和删除接口必须保持完整可用。"""
    import src.services.api as api_module

    service = FakeDocumentService()
    monkeypatch.setattr(api_module, "DocumentKnowledgeService", lambda: service)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        uploaded = await client.post(
            "/knowledge/documents",
            files={"file": ("手册.txt", b"hello", "text/plain")},
        )
        listed = await client.get("/knowledge/documents")
        detail = await client.get("/knowledge/documents/doc-001")
        reparsed = await client.post("/knowledge/documents/doc-001/reprocess")
        deleted = await client.delete("/knowledge/documents/doc-001")
        missing = await client.get("/knowledge/documents/doc-001")

    assert uploaded.status_code == 200
    assert uploaded.json()["document"]["status"] == "ready"
    assert listed.status_code == 200 and listed.json()[0]["document_id"] == "doc-001"
    assert detail.status_code == 200
    assert reparsed.status_code == 200 and reparsed.json()["message"] == "已重新解析"
    assert deleted.json() == {"deleted": True, "document_id": "doc-001"}
    assert missing.status_code == 404
