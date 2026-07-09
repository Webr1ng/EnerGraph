"""store — L2 长期记忆客户端封装

所属层：memory
依赖：datetime, logging, src.config.settings, src.schemas.memory
对接算法层：N/A
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Iterable, List, Optional, Tuple
from uuid import NAMESPACE_URL, uuid5

from pydantic import ValidationError

from src.config.settings import settings
from src.schemas.memory import (
    MemoryDelete,
    MemoryDeleteResult,
    MemoryItem,
    MemoryQuery,
    MemorySearchResult,
    MemoryWrite,
    MemoryWriteResult,
)

logger = logging.getLogger(__name__)


class MemoryStore:
    """长期记忆 store 门面。

    当前提供稳定的 InMemory fallback；当配置启用 PostgresStore 且依赖可用时，
    后续可在本类内部替换底层实现，Tool 层无需感知。
    """

    def __init__(self) -> None:
        """初始化记忆 store。"""
        self._items: Dict[Tuple[str, ...], Dict[str, MemoryItem]] = {}
        self._lock = Lock()
        self._postgres_error: Optional[str] = None
        self._postgres_context: Optional[Any] = None
        self._postgres_store: Optional[Any] = None
        self._demo_file_path = self._resolve_demo_file_path()
        if self._demo_file_path is not None:
            self._load_demo_file()
        if settings.memory.use_postgres_store:
            self._postgres_error = self._initialize_postgres_store()

    def _resolve_demo_file_path(self) -> Optional[Path]:
        """解析 demo 文件记忆路径。

        Returns:
            启用 demo 文件记忆时返回绝对路径，否则返回 None。
        """
        if not settings.memory.demo_file_store_enabled:
            return None
        path = Path(settings.memory.demo_file_store_path)
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[2] / path
        return path

    def _dump_model(self, model: Any) -> Dict[str, Any]:
        """兼容 Pydantic v1/v2 的模型序列化。

        Args:
            model: Pydantic 模型。

        Returns:
            JSON 友好的 dict。
        """
        if hasattr(model, "model_dump"):
            return model.model_dump(mode="json", exclude_none=True)
        return model.dict(exclude_none=True)

    def _load_demo_file(self) -> None:
        """从 demo 文件加载长期记忆。

        Returns:
            None。
        """
        if self._demo_file_path is None or not self._demo_file_path.exists():
            return
        try:
            payload = json.loads(self._demo_file_path.read_text(encoding="utf-8"))
            for raw_item in payload.get("items", []):
                item = MemoryItem(**raw_item)
                self._items.setdefault(tuple(item.namespace), {})[item.id] = item
        except Exception as exc:
            logger.warning(f"memory: demo file load failed: {exc}")

    def _persist_demo_file(self) -> None:
        """把内存 fallback 写入 demo 文件。

        Returns:
            None。
        """
        if self._demo_file_path is None:
            return
        try:
            self._demo_file_path.parent.mkdir(parents=True, exist_ok=True)
            items = [
                self._dump_model(item)
                for namespace_items in self._items.values()
                for item in namespace_items.values()
            ]
            payload = {
                "schema_version": 1,
                "description": "EnerGraph demo L2 long-term memory fallback; not for production.",
                "items": items,
            }
            self._demo_file_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning(f"memory: demo file persist failed: {exc}")

    def _initialize_postgres_store(self) -> Optional[str]:
        """初始化生产级 PostgresStore 连接池并执行建表迁移。

        Returns:
            成功返回 None；失败返回错误说明。
        """
        try:
            from langgraph.store.postgres import PostgresStore

            if settings.memory.postgres_pool_max_size < settings.memory.postgres_pool_min_size:
                raise ValueError("postgres pool max_size must be >= min_size")
            context = PostgresStore.from_conn_string(
                settings.memory.postgres_dsn,
                pool_config={
                    "min_size": settings.memory.postgres_pool_min_size,
                    "max_size": settings.memory.postgres_pool_max_size,
                },
            )
            store = context.__enter__()
            self._postgres_context = context
            self._postgres_store = store
            if settings.memory.postgres_setup_enabled:
                store.setup()
            logger.info(
                "L2 PostgresStore 已启用%s",
                "并完成 setup" if settings.memory.postgres_setup_enabled else "（跳过 setup）",
            )
            return None
        except Exception as exc:
            if self._postgres_context is not None:
                self._postgres_context.__exit__(None, None, None)
            self._postgres_context = None
            self._postgres_store = None
            message = f"memory: PostgresStore initialization failed: {exc}"
            logger.warning(message)
            return message

    def close(self) -> None:
        """关闭 PostgresStore 连接池。"""
        if self._postgres_context is not None:
            self._postgres_context.__exit__(None, None, None)
            self._postgres_context = None
            self._postgres_store = None

    def _postgres_item(self, raw_item: Any) -> MemoryItem:
        """将 LangGraph Store Item 转换为项目 MemoryItem。"""
        payload = dict(raw_item.value)
        payload.setdefault("id", raw_item.key)
        payload.setdefault("namespace", list(raw_item.namespace))
        payload.setdefault("created_at", raw_item.created_at)
        payload.setdefault("updated_at", raw_item.updated_at)
        if getattr(raw_item, "score", None) is not None:
            payload["score"] = raw_item.score
        return MemoryItem(**payload)

    def _put_postgres_item(self, item: MemoryItem) -> None:
        """写入单条 PostgresStore 记忆。"""
        if self._postgres_store is None:
            raise RuntimeError("PostgresStore is not initialized")
        self._postgres_store.put(
            tuple(item.namespace),
            item.id,
            self._dump_model(item),
            index=False,
        )

    def build_namespace(
        self,
        agent_id: str,
        site_id: str,
        scope: str,
        entity_id: str,
        namespace: Optional[List[str]] = None,
    ) -> List[str]:
        """构建长期记忆 namespace。

        Args:
            agent_id: Agent ID。
            site_id: 站点 ID。
            scope: 记忆范围。
            entity_id: 记忆实体 ID。
            namespace: 显式 namespace，提供后直接使用。

        Returns:
            namespace 字符串列表。

        Raises:
            ValueError: namespace 片段为空时抛出。
        """
        parts = namespace or [
            settings.memory.namespace_prefix,
            settings.memory.env,
            site_id or settings.memory.default_site_id,
            agent_id or settings.memory.default_agent_id,
            scope or "session_note",
            entity_id or "default",
        ]
        cleaned = [str(part).strip() for part in parts]
        if not cleaned or any(not part for part in cleaned):
            raise ValueError("memory namespace cannot contain empty parts")
        return cleaned

    def save(self, request: MemoryWrite) -> MemoryWriteResult:
        """写入长期记忆。

        Args:
            request: 记忆写入请求。

        Returns:
            记忆写入结果；异常时 error 字段包含 `memory: ...`。
        """
        try:
            if settings.memory.use_postgres_store and self._postgres_error:
                return MemoryWriteResult(error=self._postgres_error)

            namespace = self.build_namespace(
                agent_id=request.agent_id,
                site_id=request.site_id,
                scope=request.scope,
                entity_id=request.entity_id,
                namespace=request.namespace,
            )
            item = MemoryItem(
                content=request.content,
                namespace=namespace,
                metadata=request.metadata,
            )
            if settings.memory.use_postgres_store:
                self._put_postgres_item(item)
                return MemoryWriteResult(memory=item, namespace=namespace)
            with self._lock:
                self._items.setdefault(tuple(namespace), {})[item.id] = item
                self._persist_demo_file()
            return MemoryWriteResult(memory=item, namespace=namespace)
        except (ValidationError, ValueError) as exc:
            return MemoryWriteResult(error=f"memory: {exc}")
        except Exception as exc:
            logger.exception("save memory failed")
            return MemoryWriteResult(error=f"memory: {exc}")

    def upsert_by_tag(self, request: MemoryWrite, identity_tag: str) -> MemoryWriteResult:
        """按稳定标签新增或更新长期记忆。

        Args:
            request: 记忆写入请求。
            identity_tag: 标识同一语义记忆的标签。

        Returns:
            新增或更新后的记忆；异常时 error 字段包含 `memory: ...`。
        """
        try:
            if settings.memory.use_postgres_store and self._postgres_error:
                return MemoryWriteResult(error=self._postgres_error)
            namespace = self.build_namespace(
                agent_id=request.agent_id,
                site_id=request.site_id,
                scope=request.scope,
                entity_id=request.entity_id,
                namespace=request.namespace,
            )
            if settings.memory.use_postgres_store:
                if self._postgres_store is None:
                    raise RuntimeError("PostgresStore is not initialized")
                item_id = str(uuid5(NAMESPACE_URL, f"{'/'.join(namespace)}|{identity_tag}"))
                raw_existing = self._postgres_store.get(tuple(namespace), item_id)
                existing = self._postgres_item(raw_existing) if raw_existing else None
                item = MemoryItem(
                    id=item_id,
                    content=request.content,
                    namespace=namespace,
                    metadata=request.metadata,
                    created_at=existing.created_at if existing else datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
                self._put_postgres_item(item)
                return MemoryWriteResult(memory=item, namespace=namespace)
            with self._lock:
                namespace_items = self._items.setdefault(tuple(namespace), {})
                existing = next(
                    (
                        item
                        for item in namespace_items.values()
                        if identity_tag in item.metadata.tags
                        and item.metadata.memory_type == request.metadata.memory_type
                    ),
                    None,
                )
                if existing:
                    item = MemoryItem(
                        id=existing.id,
                        content=request.content,
                        namespace=namespace,
                        metadata=request.metadata,
                        created_at=existing.created_at,
                        updated_at=datetime.now(timezone.utc),
                    )
                else:
                    item = MemoryItem(
                        content=request.content,
                        namespace=namespace,
                        metadata=request.metadata,
                    )
                namespace_items[item.id] = item
                self._persist_demo_file()
            return MemoryWriteResult(memory=item, namespace=namespace)
        except (ValidationError, ValueError) as exc:
            return MemoryWriteResult(error=f"memory: {exc}")
        except Exception as exc:
            logger.exception("upsert memory failed")
            return MemoryWriteResult(error=f"memory: {exc}")

    def search(self, request: MemoryQuery) -> MemorySearchResult:
        """检索长期记忆。

        Args:
            request: 记忆检索请求。

        Returns:
            记忆检索结果；异常时 error 字段包含 `memory: ...`。
        """
        try:
            if settings.memory.use_postgres_store and self._postgres_error:
                return MemorySearchResult(error=self._postgres_error)

            namespace = self.build_namespace(
                agent_id=request.agent_id,
                site_id=request.site_id,
                scope=request.scope,
                entity_id=request.entity_id,
                namespace=request.namespace,
            )
            if settings.memory.use_postgres_store:
                if self._postgres_store is None:
                    raise RuntimeError("PostgresStore is not initialized")
                raw_items = self._postgres_store.search(
                    tuple(namespace),
                    limit=max(request.limit, 20),
                )
                candidates = [
                    self._postgres_item(item)
                    for item in raw_items
                    if tuple(item.namespace) == tuple(namespace)
                ]
            else:
                with self._lock:
                    candidates = list(self._items.get(tuple(namespace), {}).values())

            now = datetime.now(timezone.utc)
            memories = [
                self._rank_item(item, request.query)
                for item in candidates
                if self._matches_filters(item, request, now)
            ]
            memories.sort(key=lambda item: item.score, reverse=True)
            return MemorySearchResult(
                memories=memories[: request.limit],
                namespace=namespace,
            )
        except (ValidationError, ValueError) as exc:
            return MemorySearchResult(error=f"memory: {exc}")
        except Exception as exc:
            logger.exception("search memory failed")
            return MemorySearchResult(error=f"memory: {exc}")

    def delete(self, request: MemoryDelete) -> MemoryDeleteResult:
        """按 memory_id 与 namespace 删除单条长期记忆。

        Args:
            request: 记忆删除请求。

        Returns:
            记忆删除结果；未找到时 `deleted=False`，异常时 error 字段包含 `memory: ...`。
        """
        try:
            if settings.memory.use_postgres_store and self._postgres_error:
                return MemoryDeleteResult(memory_id=request.memory_id, error=self._postgres_error)

            namespace = self.build_namespace(
                agent_id=request.agent_id,
                site_id=request.site_id,
                scope=request.scope,
                entity_id=request.entity_id,
                namespace=request.namespace,
            )
            namespace_key = tuple(namespace)
            if settings.memory.use_postgres_store:
                if self._postgres_store is None:
                    raise RuntimeError("PostgresStore is not initialized")
                existing = self._postgres_store.get(namespace_key, request.memory_id)
                if existing is None:
                    return MemoryDeleteResult(
                        memory_id=request.memory_id,
                        deleted=False,
                        namespace=namespace,
                    )
                self._postgres_store.delete(namespace_key, request.memory_id)
                return MemoryDeleteResult(
                    memory_id=request.memory_id,
                    deleted=True,
                    namespace=namespace,
                )
            with self._lock:
                namespace_items = self._items.get(namespace_key, {})
                deleted = namespace_items.pop(request.memory_id, None) is not None
                self._persist_demo_file()
            return MemoryDeleteResult(
                memory_id=request.memory_id,
                deleted=deleted,
                namespace=namespace,
            )
        except (ValidationError, ValueError) as exc:
            return MemoryDeleteResult(memory_id=request.memory_id, error=f"memory: {exc}")
        except Exception as exc:
            logger.exception("delete memory failed")
            return MemoryDeleteResult(memory_id=request.memory_id, error=f"memory: {exc}")

    def clear(self) -> None:
        """清空内存 fallback，用于测试隔离。

        Returns:
            None。
        """
        if settings.memory.use_postgres_store and self._postgres_store is not None:
            prefix = (settings.memory.namespace_prefix, settings.memory.env)
            namespaces = self._postgres_store.list_namespaces(prefix=prefix, limit=1000)
            for namespace in namespaces:
                for item in self._postgres_store.search(namespace, limit=1000):
                    if tuple(item.namespace) == tuple(namespace):
                        self._postgres_store.delete(namespace, item.key)
            return
        with self._lock:
            self._items.clear()
            self._persist_demo_file()

    def _matches_filters(self, item: MemoryItem, request: MemoryQuery, now: datetime) -> bool:
        """判断记忆是否符合检索过滤条件。

        Args:
            item: 记忆条目。
            request: 检索请求。
            now: 当前时间。

        Returns:
            符合过滤条件返回 True。
        """
        if not request.include_expired and item.is_expired(now):
            return False
        if request.memory_types and item.metadata.memory_type not in request.memory_types:
            return False
        if not request.query.strip():
            return True
        haystacks = [
            item.content,
            item.metadata.memory_type,
            " ".join(item.metadata.tags),
        ]
        query = request.query.lower()
        return any(query in text.lower() for text in haystacks)

    def _rank_item(self, item: MemoryItem, query: str) -> MemoryItem:
        """为检索结果打简单相关度分。

        Args:
            item: 记忆条目。
            query: 查询文本。

        Returns:
            带 score 的记忆条目副本。
        """
        score = item.metadata.confidence
        if query.strip() and query.lower() in item.content.lower():
            score = min(1.0, score + 0.15)
        if hasattr(item, "model_copy"):
            return item.model_copy(update={"score": score})
        return item.copy(update={"score": score})


_STORE: Optional[MemoryStore] = None
_STORE_LOCK = Lock()


def get_memory_store() -> MemoryStore:
    """获取长期记忆 store 单例。

    Returns:
        MemoryStore 单例。
    """
    global _STORE
    with _STORE_LOCK:
        if _STORE is None:
            _STORE = MemoryStore()
        return _STORE


def reset_memory_store() -> None:
    """重置长期记忆 store 单例，用于测试。

    Returns:
        None。
    """
    global _STORE
    with _STORE_LOCK:
        if _STORE is not None:
            _STORE.close()
        _STORE = None


def _relevant_memory_queries(
    query: str,
    agent_id: str,
    site_id: str,
    thread_id: str,
    include_expired: bool,
    user_id: str = "default_user",
) -> List[MemoryQuery]:
    """构建跨 memory_type scope 的聚合检索请求。

    Args:
        query: 用户检索问题或关键词。
        agent_id: 当前 Agent ID。
        site_id: 当前站点 ID。
        thread_id: 当前会话 ID。
        include_expired: 是否包含过期记忆。

    Returns:
        MemoryQuery 列表。
    """
    thread_entity = thread_id or "unknown"
    site_entity = site_id or settings.memory.default_site_id
    return [
        MemoryQuery(
            query=query,
            agent_id=agent_id,
            site_id=site_id,
            scope="user_preference",
            entity_id=user_id or "default_user",
            limit=20,
            include_expired=include_expired,
        ),
        MemoryQuery(
            query=query,
            agent_id=agent_id,
            site_id=site_id,
            scope="user_preference",
            entity_id=thread_entity,
            limit=20,
            include_expired=include_expired,
        ),
        MemoryQuery(
            query=query,
            agent_id=agent_id,
            site_id=site_id,
            scope="site",
            entity_id=site_entity,
            limit=20,
            include_expired=include_expired,
        ),
        MemoryQuery(
            query=query,
            agent_id=agent_id,
            site_id=site_id,
            scope="safety_constraint",
            entity_id=site_entity,
            limit=20,
            include_expired=include_expired,
        ),
        MemoryQuery(
            query=query,
            agent_id=agent_id,
            site_id=site_id,
            scope="decision_history",
            entity_id=thread_entity,
            limit=20,
            include_expired=include_expired,
        ),
        MemoryQuery(
            query=query,
            agent_id=agent_id,
            site_id=site_id,
            scope="device_state",
            entity_id=site_entity,
            limit=20,
            include_expired=include_expired,
        ),
        MemoryQuery(
            query=query,
            agent_id=agent_id,
            site_id=site_id,
            scope="session_note",
            entity_id=thread_entity,
            limit=20,
            include_expired=include_expired,
        ),
    ]


def search_relevant_memories(
    query: str,
    agent_id: str,
    site_id: str,
    thread_id: str,
    limit: int = 10,
    include_expired: bool = False,
    user_id: str = "default_user",
) -> MemorySearchResult:
    """按当前上下文跨多个长期记忆 scope 聚合检索。

    聚合检索按 namespace 定位相关记忆，query 仅用于排序加分，不做硬过滤；
    这样用户询问“长期信息/运行约束”等概括问题时也能命中站点事实与约束。

    Args:
        query: 用户检索问题或关键词。
        agent_id: 当前 Agent ID。
        site_id: 当前站点 ID。
        thread_id: 当前会话 ID。
        limit: 最终返回条数上限。
        include_expired: 是否包含过期记忆。

    Returns:
        聚合后的 MemorySearchResult；失败时 error 字段包含 `memory: ...`。
    """
    try:
        store = get_memory_store()
        collected: List[MemoryItem] = []
        errors = []
        stable_preference_found = False
        for request in _relevant_memory_queries(
            query=query,
            agent_id=agent_id,
            site_id=site_id,
            thread_id=thread_id,
            include_expired=include_expired,
            user_id=user_id,
        ):
            if (
                stable_preference_found
                and request.scope == "user_preference"
                and request.entity_id == (thread_id or "unknown")
            ):
                continue
            if hasattr(request, "model_copy"):
                broad_request = request.model_copy(update={"query": ""})
            else:
                broad_request = request.copy(update={"query": ""})
            result = store.search(broad_request)
            if result.error:
                errors.append(result.error)
                continue
            if (
                request.scope == "user_preference"
                and request.entity_id == (user_id or "default_user")
                and result.memories
            ):
                stable_preference_found = True
            collected.extend(store._rank_item(item, query) for item in result.memories)

        if errors and not collected:
            return MemorySearchResult(error="; ".join(errors))

        deduped: Dict[str, MemoryItem] = {}
        for item in collected:
            key = item.id or item.content.strip()
            content_key = item.content.strip()
            if key in deduped:
                continue
            if any(existing.content.strip() == content_key for existing in deduped.values()):
                continue
            deduped[key] = item

        effective_limit = min(max(limit, 1), 10)
        memories = list(deduped.values())
        memories.sort(key=lambda item: item.score, reverse=True)
        return MemorySearchResult(
            memories=memories[:effective_limit],
            namespace=["aggregated", agent_id, site_id, thread_id or "unknown"],
        )
    except (ValidationError, ValueError) as exc:
        return MemorySearchResult(error=f"memory: {exc}")
    except Exception as exc:
        logger.exception("search relevant memories failed")
        return MemorySearchResult(error=f"memory: {exc}")


def format_memories_for_prompt(memories: Iterable[MemoryItem]) -> str:
    """将记忆条目格式化为 Prompt 注入文本。

    Args:
        memories: 记忆条目列表。

    Returns:
        Markdown 列表文本；没有记忆时返回空字符串。
    """
    lines = []
    for item in memories:
        meta = item.metadata
        tags = f" tags={','.join(meta.tags)}" if meta.tags else ""
        lines.append(f"- [{meta.memory_type} confidence={meta.confidence:.2f}{tags}] {item.content}")
    return "\n".join(lines)
