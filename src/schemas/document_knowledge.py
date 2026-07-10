"""document_knowledge — 用户文档知识库的数据模型

所属层：schemas
依赖：pydantic
对接算法层：N/A（本地 ChromaDB 文档检索）
"""
from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class DocumentStatus(str, Enum):
    """文档处理生命周期状态。"""

    UPLOADED = "uploaded"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class DocumentRecord(BaseModel):
    """文档登记记录。"""

    document_id: str
    file_name: str
    file_type: str
    content_hash: str
    file_size: int
    status: DocumentStatus
    failure_reason: Optional[str] = None
    uploaded_at: datetime
    updated_at: datetime
    chunk_count: int = 0
    retry_count: int = 0
    knowledge_base_id: str = "global"


class DocumentUploadResult(BaseModel):
    """上传或重解析操作结果。"""

    document: DocumentRecord
    duplicate: bool = False
    message: str = ""


class DocumentSource(BaseModel):
    """单个文档检索片段的可展示来源。"""

    document_id: str
    file_name: str
    page: Optional[int] = None
    section: Optional[str] = None
    chunk_index: int
    snippet: str


class DocumentKnowledgeResult(BaseModel):
    """用户文档知识库检索结果。"""

    query: str
    results: List[str] = Field(default_factory=list)
    distances: List[float] = Field(default_factory=list)
    sources: List[DocumentSource] = Field(default_factory=list)
    low_confidence: bool = True
