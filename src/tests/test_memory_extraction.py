"""test_memory_extraction — 长期记忆自动抽取写入测试

所属层：tests
依赖：pytest, src.graph.nodes, src.memory.store, src.schemas.memory
对接算法层：N/A
"""
import pytest

from src.config.settings import settings
from src.graph import nodes
from src.memory.store import get_memory_store, reset_memory_store
from src.schemas.memory import (
    MemoryCandidate,
    MemoryExtractionResult,
    MemoryQuery,
    MemorySearchResult,
)


@pytest.fixture(autouse=True)
def memory_extract_settings():
    """隔离记忆抽取相关配置与 store。"""
    original = {
        "enabled": settings.memory.enabled,
        "auto_extract_enabled": settings.memory.auto_extract_enabled,
        "extract_min_confidence": settings.memory.extract_min_confidence,
        "max_memories_per_turn": settings.memory.max_memories_per_turn,
        "device_state_default_ttl_seconds": settings.memory.device_state_default_ttl_seconds,
        "demo_file_store_enabled": settings.memory.demo_file_store_enabled,
    }
    settings.memory.enabled = True
    settings.memory.auto_extract_enabled = True
    settings.memory.extract_min_confidence = 0.65
    settings.memory.max_memories_per_turn = 3
    settings.memory.device_state_default_ttl_seconds = 86400
    settings.memory.demo_file_store_enabled = False
    reset_memory_store()
    yield
    for key, value in original.items():
        setattr(settings.memory, key, value)
    reset_memory_store()


def _state(user_input: str = "请记住以后报告先给结论") -> dict:
    """构造最小 AgentState dict。"""
    return {
        "user_input": user_input,
        "final_report": "已处理。",
        "thread_id": "thread-1",
        "agent_id": "main_graph",
        "site_id": "FJJB000001",
    }


def _candidate(content: str, memory_type: str, confidence: float = 0.9, **kwargs):
    """构造记忆候选。"""
    return MemoryCandidate(
        should_save=kwargs.pop("should_save", True),
        content=content,
        memory_type=memory_type,
        confidence=confidence,
        **kwargs,
    )


def _patch_extractor(monkeypatch, candidates):
    """替换 graph 节点中的抽取器。"""
    result = MemoryExtractionResult(candidates=candidates)
    monkeypatch.setattr(nodes, "extract_memories_from_turn", lambda **_: result)


def _search(scope: str, entity_id: str, query: str = ""):
    """按 namespace 检索测试记忆。"""
    return get_memory_store().search(
        MemoryQuery(
            query=query,
            agent_id="main_graph",
            site_id="FJJB000001",
            scope=scope,
            entity_id=entity_id,
            limit=10,
        )
    )


def test_user_preference_auto_extract_writes_user_preference(monkeypatch):
    """用户偏好自动抽取后写入 user_preference scope。"""
    _patch_extractor(
        monkeypatch,
        [_candidate("用户偏好：分析报告先给结论。", "user_preference")],
    )

    update = nodes.memory_manager_node(_state())

    assert update["memory_write_result"].error is None
    result = _search("user_preference", "thread-1", "先给结论")
    assert len(result.memories) == 1
    assert result.memories[0].metadata.memory_type == "user_preference"


def test_site_fact_auto_extract_writes_site_fact(monkeypatch):
    """站点事实自动抽取后写入 site scope。"""
    _patch_extractor(
        monkeypatch,
        [_candidate("江北工厂有一台磁悬浮主机。", "site_fact")],
    )

    nodes.memory_manager_node(_state("我们江北工厂有一台磁悬浮主机"))

    result = _search("site", "FJJB000001", "磁悬浮")
    assert len(result.memories) == 1
    assert result.memories[0].metadata.memory_type == "site_fact"


def test_safety_constraint_auto_extract_writes_safety_constraint(monkeypatch):
    """安全约束自动抽取后写入 safety_constraint scope。"""
    _patch_extractor(
        monkeypatch,
        [_candidate("储能 SOC 不得低于 20%。", "safety_constraint")],
    )

    nodes.memory_manager_node(_state("安全约束是储能 SOC 不低于 20%"))

    result = _search("safety_constraint", "FJJB000001", "SOC")
    assert len(result.memories) == 1
    assert result.memories[0].metadata.memory_type == "safety_constraint"


def test_decision_history_auto_extract_writes_without_ttl(monkeypatch):
    """已确认决策自动抽取后写入 decision_history 且不强制 TTL。"""
    _patch_extractor(
        monkeypatch,
        [_candidate("用户已确认本次采用方案 A。", "decision_history")],
    )

    nodes.memory_manager_node(_state("这次采用方案 A"))

    result = _search("decision_history", "thread-1", "方案 A")
    assert len(result.memories) == 1
    assert result.memories[0].metadata.ttl_seconds is None


def test_device_state_auto_extract_fills_default_ttl(monkeypatch):
    """临时设备状态缺 TTL 时由代码层自动补默认 TTL。"""
    _patch_extractor(
        monkeypatch,
        [_candidate("当前 2 号冷却塔处于停机状态。", "device_state")],
    )

    nodes.memory_manager_node(_state("现在 2 号冷却塔停机"))

    result = _search("device_state", "FJJB000001", "冷却塔")
    assert len(result.memories) == 1
    assert result.memories[0].metadata.ttl_seconds == 86400
    assert result.memories[0].metadata.valid_until is not None


def test_low_confidence_candidate_is_not_written(monkeypatch):
    """低置信度候选不写入。"""
    _patch_extractor(
        monkeypatch,
        [_candidate("用户可能偏好日报。", "user_preference", confidence=0.4)],
    )

    update = nodes.memory_manager_node(_state())

    assert update["memory_write_result"] is None
    assert _search("user_preference", "thread-1").memories == []


def test_irrelevant_chat_is_not_written(monkeypatch):
    """无关闲聊不写入。"""
    _patch_extractor(
        monkeypatch,
        [
            _candidate(
                "",
                "session_note",
                confidence=0.0,
                should_save=False,
                reason="闲聊不保存",
            )
        ],
    )

    update = nodes.memory_manager_node(_state("你好"))

    assert update["memory_write_result"] is None


def test_max_three_memories_per_turn(monkeypatch):
    """单轮最多写入 3 条。"""
    _patch_extractor(
        monkeypatch,
        [
            _candidate("用户偏好：报告先给结论。", "user_preference"),
            _candidate("江北工厂有一台磁悬浮主机。", "site_fact"),
            _candidate("储能 SOC 不得低于 20%。", "safety_constraint"),
            _candidate("用户已确认本次采用方案 B。", "decision_history"),
        ],
    )

    nodes.memory_manager_node(_state())

    store = get_memory_store()
    namespaces = [
        ("user_preference", "thread-1"),
        ("site", "FJJB000001"),
        ("safety_constraint", "FJJB000001"),
        ("decision_history", "thread-1"),
    ]
    counts = [
        len(
            store.search(
                MemoryQuery(
                    agent_id="main_graph",
                    site_id="FJJB000001",
                    scope=scope,
                    entity_id=entity_id,
                )
            ).memories
        )
        for scope, entity_id in namespaces
    ]
    assert counts == [1, 1, 1, 0]


def test_memory_write_failure_does_not_interrupt_final_report(monkeypatch):
    """记忆写入失败不影响本轮 final_report。"""
    _patch_extractor(
        monkeypatch,
        [_candidate("用户偏好：分析报告先给结论。", "user_preference")],
    )

    class FailingStore:
        """写入失败的 fake store。"""

        def search(self, request):
            """重复检查返回空。"""
            return MemorySearchResult(memories=[])

        def save(self, request):
            """模拟底层写入异常。"""
            raise RuntimeError("store down")

    monkeypatch.setattr("src.memory.store.get_memory_store", lambda: FailingStore())
    state = _state()
    update = nodes.memory_manager_node(state)

    assert state["final_report"] == "已处理。"
    assert update["memory_write_result"].error.startswith("memory:")


def test_auto_extract_disabled_uses_legacy_keyword_rule(monkeypatch):
    """关闭自动抽取时保留旧关键词规则。"""
    settings.memory.auto_extract_enabled = False

    def fail_if_called(**kwargs):
        raise AssertionError("extractor should not be called")

    monkeypatch.setattr(nodes, "extract_memories_from_turn", fail_if_called)
    update = nodes.memory_manager_node(_state("以后能耗分析默认按日维度展示"))

    assert update["memory_write_result"].error is None
    result = _search("session_note", "thread-1", "日维度")
    assert len(result.memories) == 1
    assert result.memories[0].content == "以后能耗分析默认按日维度展示"


def test_duplicate_candidate_is_not_written_twice(monkeypatch):
    """完全重复正文不重复写入。"""
    _patch_extractor(
        monkeypatch,
        [_candidate("江北工厂有一台磁悬浮主机。", "site_fact")],
    )

    nodes.memory_manager_node(_state("我们江北工厂有一台磁悬浮主机"))
    nodes.memory_manager_node(_state("我们江北工厂有一台磁悬浮主机"))

    result = _search("site", "FJJB000001", "磁悬浮")
    assert len(result.memories) == 1
