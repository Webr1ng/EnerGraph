"""memory_ops — 长期记忆检索与写入工具

所属层：tools
依赖：src.memory.store, src.schemas.memory
对接算法层：N/A
"""
from typing import Any, Dict, List, Optional

from pydantic import ValidationError

from src.memory.store import get_memory_store, search_relevant_memories
from src.schemas.memory import MemoryDelete, MemoryQuery, MemoryWrite, coerce_metadata


def _dump_model(model: Any) -> Dict[str, Any]:
    """兼容 Pydantic v1/v2 的模型序列化。

    Args:
        model: Pydantic 模型。

    Returns:
        JSON 友好的 dict。
    """
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json", exclude_none=True)
    return model.dict(exclude_none=True)


def search_memory(
    query: str = "",
    agent_id: str = "main_graph",
    site_id: str = "local",
    scope: str = "session_note",
    entity_id: str = "default",
    namespace: Optional[List[str]] = None,
    memory_types: Optional[List[str]] = None,
    limit: int = 5,
    include_expired: bool = False,
) -> Dict[str, Any]:
    """检索 L2 长期记忆。

    Args:
        query: 检索问题或关键词。
        agent_id: Agent ID。
        site_id: 站点 ID。
        scope: namespace scope。
        entity_id: namespace entity。
        namespace: 显式 namespace，提供后覆盖默认构建。
        memory_types: 记忆类型过滤。
        limit: 返回条数。
        include_expired: 是否返回过期记忆。

    Returns:
        MemorySearchResult 的 dict 表示；失败时包含 `{"error": "memory: ..."}`。
    """
    try:
        request = MemoryQuery(
            query=query,
            agent_id=agent_id,
            site_id=site_id,
            scope=scope,
            entity_id=entity_id,
            namespace=namespace,
            memory_types=memory_types,
            limit=limit,
            include_expired=include_expired,
        )
        result = get_memory_store().search(request)
        return _dump_model(result)
    except ValidationError as exc:
        return {"error": f"memory: {exc}"}
    except Exception as exc:
        return {"error": f"memory: {exc}"}


def search_relevant_memory(
    query: str = "",
    agent_id: str = "main_graph",
    site_id: str = "local",
    thread_id: str = "unknown",
    limit: int = 10,
    include_expired: bool = False,
    user_id: str = "default_user",
) -> Dict[str, Any]:
    """跨常用 L2 长期记忆 scope 聚合检索。

    Args:
        query: 检索问题或关键词。
        agent_id: Agent ID。
        site_id: 站点 ID。
        thread_id: 当前会话 ID，用于用户偏好、决策历史和旧 session_note。
        limit: 最终返回条数。
        include_expired: 是否返回过期记忆。
        user_id: 稳定用户 ID；演示环境默认 default_user。

    Returns:
        MemorySearchResult 的 dict 表示；失败时包含 `{"error": "memory: ..."}`。
    """
    try:
        result = search_relevant_memories(
            query=query,
            agent_id=agent_id,
            site_id=site_id,
            thread_id=thread_id,
            limit=limit,
            include_expired=include_expired,
            user_id=user_id,
        )
        return _dump_model(result)
    except ValidationError as exc:
        return {"error": f"memory: {exc}"}
    except Exception as exc:
        return {"error": f"memory: {exc}"}


def save_memory(
    content: str,
    agent_id: str = "main_graph",
    site_id: str = "local",
    scope: str = "session_note",
    entity_id: str = "default",
    namespace: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    memory_key: str = "",
    user_id: str = "default_user",
) -> Dict[str, Any]:
    """写入 L2 长期记忆。

    Args:
        content: 记忆正文。
        agent_id: Agent ID。
        site_id: 站点 ID。
        scope: namespace scope。
        entity_id: namespace entity。
        namespace: 显式 namespace，提供后覆盖默认构建。
        metadata: 记忆元数据。
        memory_key: 用户偏好的稳定语义键；memory_type=user_preference 时必填。
        user_id: 稳定用户 ID；演示环境默认 default_user。

    Returns:
        MemoryWriteResult 的 dict 表示；失败时包含 `{"error": "memory: ..."}`。
    """
    try:
        memory_metadata = coerce_metadata(metadata, agent_id=agent_id, site_id=site_id)
        identity_tag = ""
        if memory_metadata.memory_type == "user_preference":
            normalized_key = memory_key.strip()
            if not normalized_key:
                return {"error": "memory: user_preference requires memory_key"}
            identity_tag = f"memory_key:{normalized_key}"
            memory_metadata.tags = [
                tag for tag in memory_metadata.tags if not tag.startswith("memory_key:")
            ]
            memory_metadata.tags.append(identity_tag)
            scope = "user_preference"
            entity_id = user_id.strip() or "default_user"
            namespace = None
        request = MemoryWrite(
            content=content,
            agent_id=agent_id,
            site_id=site_id,
            scope=scope,
            entity_id=entity_id,
            namespace=namespace,
            metadata=memory_metadata,
        )
        if identity_tag:
            result = get_memory_store().upsert_by_tag(request, identity_tag)
        else:
            result = get_memory_store().save(request)
        return _dump_model(result)
    except ValidationError as exc:
        return {"error": f"memory: {exc}"}
    except Exception as exc:
        return {"error": f"memory: {exc}"}


def delete_memory(
    memory_id: str,
    agent_id: str = "main_graph",
    site_id: str = "local",
    scope: str = "session_note",
    entity_id: str = "default",
    namespace: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """显式删除 L2 长期记忆。

    Args:
        memory_id: 要删除的记忆 ID。
        agent_id: Agent ID。
        site_id: 站点 ID。
        scope: namespace scope。
        entity_id: namespace entity。
        namespace: 显式 namespace，提供后覆盖默认构建。

    Returns:
        MemoryDeleteResult 的 dict 表示；失败时包含 `{"error": "memory: ..."}`。
    """
    try:
        request = MemoryDelete(
            memory_id=memory_id,
            agent_id=agent_id,
            site_id=site_id,
            scope=scope,
            entity_id=entity_id,
            namespace=namespace,
        )
        result = get_memory_store().delete(request)
        return _dump_model(result)
    except ValidationError as exc:
        return {"error": f"memory: {exc}"}
    except Exception as exc:
        return {"error": f"memory: {exc}"}
