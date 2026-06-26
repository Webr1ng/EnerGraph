"""memory — 记忆模块 Tool I/O 数据模型

所属层：schemas
依赖：pydantic
对接算法层：N/A
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

try:
    from pydantic import field_validator, model_validator

    _PYDANTIC_V2 = True
except ImportError:
    from pydantic import root_validator, validator

    _PYDANTIC_V2 = False


MemoryType = Literal[
    "user_preference",
    "site_fact",
    "decision_history",
    "device_state",
    "safety_constraint",
    "session_note",
]

TEMPORARY_MEMORY_TYPES = {"device_state"}


class MemoryMetadata(BaseModel):
    """长期记忆元数据。"""
    memory_type: MemoryType = Field(default="session_note", description="记忆类型")
    source_thread_id: str = Field(default="unknown", description="来源会话 ID")
    site_id: str = Field(default="local", description="站点 ID")
    agent_id: str = Field(default="main_graph", description="写入 Agent ID")
    confidence: float = Field(default=0.8, ge=0, le=1, description="记忆置信度")
    valid_until: Optional[datetime] = Field(default=None, description="有效期截止时间")
    ttl_seconds: Optional[int] = Field(default=None, ge=0, description="相对 TTL，0/None 表示长期有效")
    tags: List[str] = Field(default_factory=list, description="检索标签")

    if _PYDANTIC_V2:
        @field_validator("source_thread_id", "site_id", "agent_id")
        @classmethod
        def _strip_required_text(cls, value: str) -> str:
            """清理必填文本字段。"""
            value = value.strip()
            if not value:
                raise ValueError("memory metadata text fields cannot be empty")
            return value

        @model_validator(mode="after")
        def _temporary_memory_requires_ttl(self) -> "MemoryMetadata":
            """校验临时记忆必须带时效。"""
            if self.memory_type in TEMPORARY_MEMORY_TYPES and not self.valid_until and not self.ttl_seconds:
                raise ValueError("temporary memory requires valid_until or ttl_seconds")
            return self
    else:
        @validator("source_thread_id", "site_id", "agent_id")
        @classmethod
        def _strip_required_text(cls, value: str) -> str:
            """清理必填文本字段。"""
            value = value.strip()
            if not value:
                raise ValueError("memory metadata text fields cannot be empty")
            return value

        @root_validator(skip_on_failure=True)
        def _temporary_memory_requires_ttl(cls, values: Dict[str, Any]) -> Dict[str, Any]:
            """校验临时记忆必须带时效。"""
            memory_type = values.get("memory_type")
            valid_until = values.get("valid_until")
            ttl_seconds = values.get("ttl_seconds")
            if memory_type in TEMPORARY_MEMORY_TYPES and not valid_until and not ttl_seconds:
                raise ValueError("temporary memory requires valid_until or ttl_seconds")
            return values


class MemoryCandidate(BaseModel):
    """单条长期记忆抽取候选。"""
    should_save: bool = Field(default=False, description="是否建议写入长期记忆")
    content: str = Field(default="", description="简洁、可独立理解的记忆正文")
    memory_type: MemoryType = Field(default="session_note", description="候选记忆类型")
    confidence: float = Field(default=0.0, ge=0, le=1, description="候选置信度")
    ttl_seconds: Optional[int] = Field(default=None, ge=0, description="候选相对 TTL")
    tags: List[str] = Field(default_factory=list, description="候选标签")
    reason: str = Field(default="", description="抽取或跳过原因")


class MemoryExtractionResult(BaseModel):
    """单轮长期记忆抽取结果。"""
    candidates: List[MemoryCandidate] = Field(default_factory=list, description="候选记忆列表")
    skip_reason: Optional[str] = Field(default=None, description="整轮跳过原因")


class MemoryItem(BaseModel):
    """长期记忆条目。"""
    id: str = Field(default_factory=lambda: str(uuid4()), description="记忆 ID")
    content: str = Field(..., min_length=1, description="记忆正文")
    namespace: List[str] = Field(default_factory=list, description="LangGraph store namespace")
    metadata: MemoryMetadata = Field(default_factory=MemoryMetadata, description="记忆元数据")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    score: float = Field(default=1.0, ge=0, le=1, description="检索相关度")

    if _PYDANTIC_V2:
        @model_validator(mode="after")
        def _apply_ttl(self) -> "MemoryItem":
            """把 ttl_seconds 转换为 valid_until。"""
            ttl = self.metadata.ttl_seconds
            if ttl and ttl > 0 and self.metadata.valid_until is None:
                self.metadata.valid_until = self.created_at + timedelta(seconds=ttl)
            return self
    else:
        @root_validator(skip_on_failure=True)
        def _apply_ttl(cls, values: Dict[str, Any]) -> Dict[str, Any]:
            """把 ttl_seconds 转换为 valid_until。"""
            metadata = values.get("metadata")
            created_at = values.get("created_at")
            if metadata is None or created_at is None:
                return values
            ttl = metadata.ttl_seconds
            if ttl and ttl > 0 and metadata.valid_until is None:
                metadata.valid_until = created_at + timedelta(seconds=ttl)
            return values

    def is_expired(self, now: Optional[datetime] = None) -> bool:
        """判断记忆是否已过期。

        Args:
            now: 当前时间，默认使用 UTC 当前时间。

        Returns:
            已过期返回 True，否则返回 False。
        """
        if self.metadata.valid_until is None:
            return False
        current = now or datetime.now(timezone.utc)
        valid_until = self.metadata.valid_until
        if valid_until.tzinfo is None:
            valid_until = valid_until.replace(tzinfo=timezone.utc)
        return valid_until <= current


class MemoryQuery(BaseModel):
    """记忆检索请求。"""
    query: str = Field(default="", description="检索问题或关键词")
    agent_id: str = Field(default="main_graph", description="Agent ID")
    site_id: str = Field(default="local", description="站点 ID")
    scope: str = Field(default="session_note", description="namespace scope")
    entity_id: str = Field(default="default", description="namespace entity")
    namespace: Optional[List[str]] = Field(default=None, description="显式 namespace，提供后覆盖默认构建")
    memory_types: Optional[List[MemoryType]] = Field(default=None, description="记忆类型过滤")
    limit: int = Field(default=5, ge=1, le=20, description="返回条数")
    include_expired: bool = Field(default=False, description="是否返回过期记忆")


class MemoryWrite(BaseModel):
    """记忆写入请求。"""
    content: str = Field(..., min_length=1, description="记忆正文")
    agent_id: str = Field(default="main_graph", description="Agent ID")
    site_id: str = Field(default="local", description="站点 ID")
    scope: str = Field(default="session_note", description="namespace scope")
    entity_id: str = Field(default="default", description="namespace entity")
    namespace: Optional[List[str]] = Field(default=None, description="显式 namespace，提供后覆盖默认构建")
    metadata: MemoryMetadata = Field(default_factory=MemoryMetadata, description="记忆元数据")


class MemorySearchResult(BaseModel):
    """记忆检索结果。"""
    memories: List[MemoryItem] = Field(default_factory=list, description="命中的记忆")
    namespace: List[str] = Field(default_factory=list, description="实际检索 namespace")
    error: Optional[str] = Field(default=None, description="错误信息")


class MemoryWriteResult(BaseModel):
    """记忆写入结果。"""
    memory: Optional[MemoryItem] = Field(default=None, description="写入后的记忆")
    namespace: List[str] = Field(default_factory=list, description="实际写入 namespace")
    error: Optional[str] = Field(default=None, description="错误信息")


def coerce_metadata(data: Optional[Dict[str, Any]], agent_id: str, site_id: str) -> MemoryMetadata:
    """把工具入参转换为 MemoryMetadata。

    Args:
        data: 调用方传入的元数据字典。
        agent_id: 默认 Agent ID。
        site_id: 默认站点 ID。

    Returns:
        MemoryMetadata 实例。

    Raises:
        pydantic.ValidationError: 元数据不合法时由 Pydantic 抛出。
    """
    payload = dict(data or {})
    payload.setdefault("agent_id", agent_id)
    payload.setdefault("site_id", site_id)
    payload.setdefault("source_thread_id", "unknown")
    return MemoryMetadata(**payload)
