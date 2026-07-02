"""test_memory_store — L2 长期记忆 store 封装测试

所属层：tests
依赖：pytest, src.memory.store, src.schemas.memory
对接算法层：N/A
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src.config.settings import settings
from src.memory.store import get_memory_store, reset_memory_store
from src.schemas.memory import MemoryMetadata, MemoryQuery, MemoryWrite


@pytest.fixture(autouse=True)
def clean_memory_store():
    """每个用例清空内存 store。"""
    original_demo_enabled = settings.memory.demo_file_store_enabled
    original_demo_path = settings.memory.demo_file_store_path
    original_use_postgres = settings.memory.use_postgres_store
    settings.memory.demo_file_store_enabled = False
    settings.memory.use_postgres_store = False
    reset_memory_store()
    yield
    settings.memory.demo_file_store_enabled = original_demo_enabled
    settings.memory.demo_file_store_path = original_demo_path
    settings.memory.use_postgres_store = original_use_postgres
    reset_memory_store()


class _FakePostgresStore:
    """模拟 LangGraph PostgresStore 的共享持久化后端。"""

    def __init__(self):
        self.items = {}
        self.setup_calls = 0

    def setup(self):
        """记录 setup 调用。"""
        self.setup_calls += 1

    def put(self, namespace, key, value, index=None):
        """按 namespace/key 原子覆盖。"""
        now = datetime.now(timezone.utc)
        previous = self.items.get((namespace, key))
        self.items[(namespace, key)] = SimpleNamespace(
            namespace=namespace,
            key=key,
            value=value,
            created_at=previous.created_at if previous else now,
            updated_at=now,
            score=None,
        )

    def get(self, namespace, key):
        """按 key 获取。"""
        return self.items.get((namespace, key))

    def search(self, namespace, limit=10, **kwargs):
        """按 namespace 前缀检索。"""
        return [
            item
            for (item_namespace, _), item in self.items.items()
            if item_namespace[: len(namespace)] == namespace
        ][:limit]

    def list_namespaces(self, prefix=None, limit=100, **kwargs):
        """列出 namespace。"""
        namespaces = {namespace for namespace, _ in self.items}
        if prefix:
            namespaces = {namespace for namespace in namespaces if namespace[: len(prefix)] == prefix}
        return list(namespaces)[:limit]

    def delete(self, namespace, key):
        """删除记录。"""
        self.items.pop((namespace, key), None)


class _FakePostgresContext:
    """模拟 from_conn_string 返回的 context manager。"""

    def __init__(self, store):
        self.store = store
        self.closed = False

    def __enter__(self):
        return self.store

    def __exit__(self, exc_type, exc, traceback):
        self.closed = True


def test_save_and_search_memory():
    """正常写入并检索长期记忆。"""
    store = get_memory_store()
    metadata = MemoryMetadata(
        memory_type="user_preference",
        source_thread_id="thread-1",
        site_id="FJJB000001",
        agent_id="powerai",
        confidence=0.9,
        tags=["dispatch"],
    )
    write_result = store.save(
        MemoryWrite(
            content="用户偏好优先使用峰谷套利策略",
            agent_id="powerai",
            site_id="FJJB000001",
            scope="session_note",
            entity_id="thread-1",
            metadata=metadata,
        )
    )

    assert write_result.error is None
    assert write_result.memory is not None

    search_result = store.search(
        MemoryQuery(
            query="峰谷套利",
            agent_id="powerai",
            site_id="FJJB000001",
            scope="session_note",
            entity_id="thread-1",
        )
    )

    assert search_result.error is None
    assert len(search_result.memories) == 1
    assert search_result.memories[0].content == "用户偏好优先使用峰谷套利策略"


def test_upsert_by_tag_updates_in_place():
    """同一稳定标签更新原记忆并保留 ID。"""
    store = get_memory_store()
    identity_tag = "memory_key:energy_analysis_report_order"
    metadata = MemoryMetadata(
        memory_type="user_preference",
        source_thread_id="thread-1",
        site_id="FJJB000001",
        agent_id="main_graph",
        confidence=0.9,
        tags=[identity_tag],
    )
    first = store.upsert_by_tag(
        MemoryWrite(
            content="用户偏好：先给结论，再给数据。",
            site_id="FJJB000001",
            scope="user_preference",
            entity_id="default_user",
            metadata=metadata,
        ),
        identity_tag,
    )
    second = store.upsert_by_tag(
        MemoryWrite(
            content="用户偏好：先给数据，最后给结论。",
            site_id="FJJB000001",
            scope="user_preference",
            entity_id="default_user",
            metadata=metadata,
        ),
        identity_tag,
    )

    result = store.search(
        MemoryQuery(
            site_id="FJJB000001",
            scope="user_preference",
            entity_id="default_user",
        )
    )
    assert first.memory.id == second.memory.id
    assert len(result.memories) == 1
    assert result.memories[0].content == "用户偏好：先给数据，最后给结论。"


def test_expired_memory_is_filtered_by_default():
    """过期记忆默认不返回。"""
    store = get_memory_store()
    expired_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    metadata = MemoryMetadata(
        memory_type="device_state",
        source_thread_id="thread-1",
        site_id="FJJB000001",
        agent_id="powerai",
        valid_until=expired_at,
    )
    store.save(
        MemoryWrite(
            content="1 号储能柜当前 SOC 为 20%",
            agent_id="powerai",
            site_id="FJJB000001",
            scope="session_note",
            entity_id="thread-1",
            metadata=metadata,
        )
    )

    result = store.search(
        MemoryQuery(
            query="SOC",
            agent_id="powerai",
            site_id="FJJB000001",
            scope="session_note",
            entity_id="thread-1",
        )
    )

    assert result.memories == []


def test_temporary_memory_requires_ttl():
    """临时记忆缺少 TTL/valid_until 时校验失败。"""
    with pytest.raises(ValueError):
        MemoryMetadata(
            memory_type="device_state",
            source_thread_id="thread-1",
            site_id="FJJB000001",
            agent_id="powerai",
        )


def test_invalid_namespace_returns_error():
    """显式 namespace 含空片段时返回 error dict 语义。"""
    store = get_memory_store()
    result = store.search(
        MemoryQuery(
            query="test",
            agent_id="powerai",
            site_id="FJJB000001",
            namespace=["energraph", ""],
        )
    )

    assert result.error is not None
    assert result.error.startswith("memory:")


def test_demo_file_store_survives_store_reset(tmp_path):
    """demo 文件落盘开启时，重建 store 后仍能检索记忆。"""
    settings.memory.demo_file_store_enabled = True
    settings.memory.demo_file_store_path = str(tmp_path / "memories.json")
    reset_memory_store()

    store = get_memory_store()
    metadata = MemoryMetadata(
        memory_type="user_preference",
        source_thread_id="thread-demo",
        site_id="FJJB000001",
        agent_id="main_graph",
        confidence=0.8,
    )
    write_result = store.save(
        MemoryWrite(
            content="用户偏好能耗分析默认按日维度展示，并优先关注 COP",
            agent_id="main_graph",
            site_id="FJJB000001",
            scope="session_note",
            entity_id="thread-demo",
            metadata=metadata,
        )
    )
    assert write_result.error is None

    reset_memory_store()
    reloaded_store = get_memory_store()
    search_result = reloaded_store.search(
        MemoryQuery(
            query="COP",
            agent_id="main_graph",
            site_id="FJJB000001",
            scope="session_note",
            entity_id="thread-demo",
        )
    )

    assert search_result.error is None
    assert len(search_result.memories) == 1
    assert "日维度" in search_result.memories[0].content


def test_postgres_store_setup_save_search_and_close(monkeypatch):
    """启用 L2 PostgreSQL 时初始化表、持久化检索并在 reset 时关闭连接池。"""
    from langgraph.store.postgres import PostgresStore

    backend = _FakePostgresStore()
    contexts = []

    def fake_from_conn_string(*args, **kwargs):
        context = _FakePostgresContext(backend)
        contexts.append(context)
        return context

    monkeypatch.setattr(PostgresStore, "from_conn_string", fake_from_conn_string)
    settings.memory.use_postgres_store = True
    reset_memory_store()

    store = get_memory_store()
    result = store.save(
        MemoryWrite(
            content="用户偏好：回答简洁。",
            site_id="FJJB000001",
            scope="user_preference",
            entity_id="default_user",
            metadata=MemoryMetadata(memory_type="user_preference"),
        )
    )
    search_result = store.search(
        MemoryQuery(
            site_id="FJJB000001",
            scope="user_preference",
            entity_id="default_user",
        )
    )

    assert result.error is None
    assert backend.setup_calls == 1
    assert len(search_result.memories) == 1
    reset_memory_store()
    assert contexts[0].closed is True


def test_postgres_upsert_key_is_stable_across_store_instances(monkeypatch):
    """多实例按同一 memory_key 写入时复用确定性主键，不产生重复行。"""
    from langgraph.store.postgres import PostgresStore

    backend = _FakePostgresStore()
    monkeypatch.setattr(
        PostgresStore,
        "from_conn_string",
        lambda *args, **kwargs: _FakePostgresContext(backend),
    )
    settings.memory.use_postgres_store = True
    metadata = MemoryMetadata(
        memory_type="user_preference",
        tags=["memory_key:energy_analysis_report_order"],
    )
    request = MemoryWrite(
        content="用户偏好：先给结论。",
        site_id="FJJB000001",
        scope="user_preference",
        entity_id="default_user",
        metadata=metadata,
    )

    first = get_memory_store().upsert_by_tag(request, "memory_key:energy_analysis_report_order")
    reset_memory_store()
    request.content = "用户偏好：先给数据，最后给结论。"
    second_store = get_memory_store()
    second = second_store.upsert_by_tag(request, "memory_key:energy_analysis_report_order")
    result = second_store.search(
        MemoryQuery(
            site_id="FJJB000001",
            scope="user_preference",
            entity_id="default_user",
        )
    )

    assert first.memory.id == second.memory.id
    assert len(backend.items) == 1
    assert len(result.memories) == 1
    assert result.memories[0].content == "用户偏好：先给数据，最后给结论。"
