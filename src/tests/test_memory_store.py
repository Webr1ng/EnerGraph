"""test_memory_store — L2 长期记忆 store 封装测试

所属层：tests
依赖：pytest, src.memory.store, src.schemas.memory
对接算法层：N/A
"""
from datetime import datetime, timedelta, timezone

import pytest

from src.config.settings import settings
from src.memory.store import get_memory_store, reset_memory_store
from src.schemas.memory import MemoryMetadata, MemoryQuery, MemoryWrite


@pytest.fixture(autouse=True)
def clean_memory_store():
    """每个用例清空内存 store。"""
    original_demo_enabled = settings.memory.demo_file_store_enabled
    original_demo_path = settings.memory.demo_file_store_path
    reset_memory_store()
    yield
    settings.memory.demo_file_store_enabled = original_demo_enabled
    settings.memory.demo_file_store_path = original_demo_path
    reset_memory_store()


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
