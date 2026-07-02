"""test_memory_relevant_search — 长期记忆跨 scope 聚合检索测试

所属层：tests
依赖：datetime, pytest, src.memory.store, src.graph.nodes
对接算法层：N/A
"""
from datetime import datetime, timedelta, timezone

import pytest

from src.config.settings import settings
from src.graph import nodes
from src.memory.store import get_memory_store, reset_memory_store, search_relevant_memories
from src.schemas.memory import MemoryMetadata, MemoryQuery, MemoryWrite


@pytest.fixture(autouse=True)
def clean_memory_store():
    """隔离聚合检索测试配置与 store。"""
    original_enabled = settings.memory.enabled
    original_demo_enabled = settings.memory.demo_file_store_enabled
    settings.memory.enabled = True
    settings.memory.demo_file_store_enabled = False
    reset_memory_store()
    yield
    settings.memory.enabled = original_enabled
    settings.memory.demo_file_store_enabled = original_demo_enabled
    reset_memory_store()


def _write_memory(
    content: str,
    memory_type: str,
    scope: str,
    entity_id: str,
    site_id: str = "FJJB000001",
    thread_id: str = "thread-1",
    ttl_seconds: int | None = None,
    valid_until=None,
):
    """写入测试记忆。"""
    metadata = MemoryMetadata(
        memory_type=memory_type,
        source_thread_id=thread_id,
        site_id=site_id,
        agent_id="main_graph",
        confidence=0.9,
        ttl_seconds=ttl_seconds,
        valid_until=valid_until,
    )
    return get_memory_store().save(
        MemoryWrite(
            content=content,
            agent_id="main_graph",
            site_id=site_id,
            scope=scope,
            entity_id=entity_id,
            metadata=metadata,
        )
    )


def _aggregate(query: str, site_id: str = "FJJB000001"):
    """执行默认聚合检索。"""
    return search_relevant_memories(
        query=query,
        agent_id="main_graph",
        site_id=site_id,
        thread_id="thread-1",
    )


def test_relevant_search_returns_site_fact():
    """写入 site_fact 后，长期信息问题能聚合检索到。"""
    _write_memory("江北工厂有一台磁悬浮主机。", "site_fact", "site", "FJJB000001")

    result = _aggregate("江北工厂有哪些长期信息")

    assert result.error is None
    assert any("磁悬浮主机" in item.content for item in result.memories)


def test_relevant_search_returns_safety_constraint_without_keyword_match():
    """写入 safety_constraint 后，概括性运行约束问题能检索到。"""
    _write_memory("储能 SOC 不得低于 20%。", "safety_constraint", "safety_constraint", "FJJB000001")

    result = _aggregate("运行约束是什么")

    assert result.error is None
    assert any("SOC 不得低于 20%" in item.content for item in result.memories)


def test_relevant_search_filters_expired_device_state():
    """device_state 未过期可检索，过期后默认不返回。"""
    _write_memory(
        "当前 2 号冷却塔处于停机状态。",
        "device_state",
        "device_state",
        "FJJB000001",
        ttl_seconds=3600,
    )
    expired_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    _write_memory(
        "当前 3 号冷却塔处于告警状态。",
        "device_state",
        "device_state",
        "FJJB000001",
        valid_until=expired_at,
    )

    result = _aggregate("设备状态")

    contents = [item.content for item in result.memories]
    assert "当前 2 号冷却塔处于停机状态。" in contents
    assert "当前 3 号冷却塔处于告警状态。" not in contents


def test_relevant_search_returns_legacy_session_note():
    """旧 session_note 记忆仍能被聚合检索。"""
    _write_memory("以后能耗分析默认按日维度展示。", "user_preference", "session_note", "thread-1")

    result = _aggregate("长期信息")

    assert any("日维度" in item.content for item in result.memories)


def test_user_preference_uses_stable_user_across_threads():
    """用户偏好按稳定 user_id 检索，不随 thread_id 切换丢失。"""
    _write_memory(
        "用户偏好：能耗分析先给结论。",
        "user_preference",
        "user_preference",
        "default_user",
        thread_id="thread-old",
    )

    result = search_relevant_memories(
        query="我保存了哪些长期偏好",
        agent_id="main_graph",
        site_id="FJJB000001",
        thread_id="thread-new",
        user_id="default_user",
    )

    assert any("先给结论" in item.content for item in result.memories)


def test_stable_user_preference_suppresses_legacy_thread_value():
    """已有稳定用户偏好时不混入旧 thread namespace 的冲突值。"""
    _write_memory(
        "用户偏好：能耗分析先给结论。",
        "user_preference",
        "user_preference",
        "thread-1",
    )
    _write_memory(
        "用户偏好：能耗分析先给数据，最后给结论。",
        "user_preference",
        "user_preference",
        "default_user",
    )

    result = _aggregate("我保存了哪些长期偏好")
    contents = [item.content for item in result.memories]

    assert "用户偏好：能耗分析先给数据，最后给结论。" in contents
    assert "用户偏好：能耗分析先给结论。" not in contents


def test_memory_recall_query_bypasses_business_llm(monkeypatch):
    """显式记忆查询直接读取结构化结果，不误调用 HVAC 等业务工具。"""
    _write_memory(
        "用户偏好：能耗分析先给结论。",
        "user_preference",
        "user_preference",
        "default_user",
    )
    monkeypatch.setattr(
        nodes,
        "_get_llm",
        lambda **_: (_ for _ in ()).throw(AssertionError("memory recall must bypass LLM routing")),
    )

    updates = nodes.cognitive_parser_node(
        {
            "user_input": "请告诉我保存了哪些长期偏好。",
            "thread_id": "thread-new",
            "user_id": "default_user",
            "agent_id": "main_graph",
            "site_id": "FJJB000001",
        }
    )

    response = updates["messages"][-1]
    assert not response.tool_calls
    assert "先给结论" in response.content


@pytest.mark.parametrize(
    "query",
    [
        "你记得我有什么偏好吗？",
        "你记录过我的哪些偏好？",
        "目前保存了什么偏好？",
    ],
)
def test_memory_recall_query_recognizes_natural_variants(query):
    """常见自然语言偏好查询均命中确定性记忆查询路径。"""
    assert nodes._is_memory_recall_query(query)


@pytest.mark.parametrize(
    "query",
    [
        "请更新我的偏好：以后先给数据，最后给结论。",
        "把我的偏好改为回答简洁。",
        "删除我的报告展示偏好。",
    ],
)
def test_memory_mutation_is_not_misclassified_as_recall(query):
    """偏好更新/删除指令不得被显式查询捷径拦截。"""
    assert not nodes._is_memory_recall_query(query)


@pytest.mark.parametrize(
    "query",
    [
        "请修改报警页面的筛选条件。",
        "以后天气会怎么样？",
        "默认页面是什么？",
    ],
)
def test_business_requests_are_not_misclassified_as_memory_writes(query):
    """普通修改、未来问题和默认值查询不得抑制业务回答。"""
    assert not nodes.is_explicit_memory_write_request(query)


def test_relevant_search_isolated_by_site_id():
    """不同 site_id 的站点事实不互通。"""
    _write_memory("江北工厂有一台磁悬浮主机。", "site_fact", "site", "FJJB000001")
    _write_memory(
        "河西工厂有两台冷却塔。",
        "site_fact",
        "site",
        "OTHER_SITE",
        site_id="OTHER_SITE",
    )

    result = _aggregate("长期信息", site_id="OTHER_SITE")

    contents = [item.content for item in result.memories]
    assert "河西工厂有两台冷却塔。" in contents
    assert "江北工厂有一台磁悬浮主机。" not in contents


def test_inject_memory_context_uses_relevant_search():
    """cognitive_parser 入口注入使用聚合检索而不是只查 session_note。"""
    _write_memory("江北工厂有一台磁悬浮主机。", "site_fact", "site", "FJJB000001")
    _write_memory("储能 SOC 不得低于 20%。", "safety_constraint", "safety_constraint", "FJJB000001")
    _write_memory("用户已确认本次采用方案 A。", "decision_history", "decision_history", "thread-1")
    _write_memory(
        "当前 2 号冷却塔处于停机状态。",
        "device_state",
        "device_state",
        "FJJB000001",
        ttl_seconds=3600,
    )

    system_content, updates = nodes._inject_memory_context(
        {
            "user_input": "你知道江北工厂有哪些长期信息和运行约束吗？",
            "thread_id": "thread-1",
            "agent_id": "main_graph",
            "site_id": "FJJB000001",
        },
        "system",
    )

    assert "磁悬浮主机" in system_content
    assert "SOC 不得低于 20%" in system_content
    assert "方案 A" in system_content
    assert "2 号冷却塔" in system_content
    assert len(updates["memory_search_result"].memories) == 4


def test_explicit_search_memory_still_uses_single_namespace():
    """原 search_memory 行为仍保留显式单 namespace 检索能力。"""
    _write_memory("江北工厂有一台磁悬浮主机。", "site_fact", "site", "FJJB000001")

    session_result = get_memory_store().search(
        MemoryQuery(
            query="江北工厂",
            agent_id="main_graph",
            site_id="FJJB000001",
            scope="session_note",
            entity_id="thread-1",
        )
    )
    site_result = get_memory_store().search(
        MemoryQuery(
            query="江北工厂",
            agent_id="main_graph",
            site_id="FJJB000001",
            scope="site",
            entity_id="FJJB000001",
        )
    )

    assert session_result.memories == []
    assert len(site_result.memories) == 1
