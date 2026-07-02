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
        source=kwargs.pop("source", "user_explicit"),
        retrievable=kwargs.pop("retrievable", False),
        user_confirmed=kwargs.pop("user_confirmed", True),
        memory_key=kwargs.pop(
            "memory_key",
            "energy_analysis_report_order" if memory_type == "user_preference" else "",
        ),
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
    result = _search("user_preference", "default_user", "先给结论")
    assert len(result.memories) == 1
    assert result.memories[0].metadata.memory_type == "user_preference"
    assert update["memory_feedback"] == "已保存长期偏好：用户偏好：分析报告先给结论。"


def test_non_retrievable_site_fact_writes_site_fact(monkeypatch):
    """用户确认且系统不可查询的站点事实写入 site scope。"""
    _patch_extractor(
        monkeypatch,
        [_candidate("江北工厂冬季生产线不使用工艺冷却。", "site_fact")],
    )

    nodes.memory_manager_node(_state("请记住，我们江北工厂冬季生产线不使用工艺冷却"))

    result = _search("site", "FJJB000001", "工艺冷却")
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


def test_device_state_is_never_auto_written(monkeypatch):
    """可实时查询的设备状态不进入 L2 长期记忆。"""
    _patch_extractor(
        monkeypatch,
        [_candidate("当前 2 号冷却塔处于停机状态。", "device_state")],
    )

    nodes.memory_manager_node(_state("现在 2 号冷却塔停机"))

    result = _search("device_state", "FJJB000001", "冷却塔")
    assert result.memories == []


def test_explicit_device_state_save_request_returns_rejection_feedback(monkeypatch):
    """明确要求保存实时设备状态时，最终反馈以质量闸门结果为准。"""
    _patch_extractor(
        monkeypatch,
        [_candidate("当前 2 号冷却塔处于停机状态。", "device_state")],
    )

    update = nodes.memory_manager_node(_state("请记住：当前 2 号冷却塔处于停机状态"))

    assert update["memory_write_result"] is None
    assert update["memory_feedback"].startswith("未写入长期记忆")
    assert update["final_report"] == update["memory_feedback"]


def test_retrievable_tool_data_is_not_written(monkeypatch):
    """Tool/API 可重新查询的数据摘要不写入长期记忆。"""
    _patch_extractor(
        monkeypatch,
        [
            _candidate(
                "2026-06-26 光伏发电量为 404 kWh。",
                "site_fact",
                source="tool_result",
                retrievable=True,
            )
        ],
    )

    update = nodes.memory_manager_node(_state("今天光伏发电量是多少？"))

    assert update["memory_write_result"] is None
    assert _search("site", "FJJB000001").memories == []


def test_assistant_only_fact_is_not_written(monkeypatch):
    """仅由助手回答产生的事实不写入长期记忆。"""
    _patch_extractor(
        monkeypatch,
        [
            _candidate(
                "用户适合采用稳健型方案。",
                "decision_history",
                source="assistant",
                user_confirmed=False,
            )
        ],
    )

    update = nodes.memory_manager_node(_state("请给我推荐一个方案"))

    assert update["memory_write_result"] is None
    assert _search("decision_history", "thread-1").memories == []


def test_unconfirmed_constraint_is_not_written(monkeypatch):
    """用户未确认的安全约束不写入长期记忆。"""
    _patch_extractor(
        monkeypatch,
        [
            _candidate(
                "储能 SOC 不得低于 20%。",
                "safety_constraint",
                user_confirmed=False,
            )
        ],
    )

    update = nodes.memory_manager_node(_state("SOC 下限一般设多少？"))

    assert update["memory_write_result"] is None
    assert _search("safety_constraint", "FJJB000001").memories == []


def test_low_confidence_candidate_is_not_written(monkeypatch):
    """低置信度候选不写入。"""
    _patch_extractor(
        monkeypatch,
        [_candidate("用户可能偏好日报。", "user_preference", confidence=0.4)],
    )

    update = nodes.memory_manager_node(_state())

    assert update["memory_write_result"] is None
    assert _search("user_preference", "default_user").memories == []


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
        ("user_preference", "default_user"),
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
    result = _search("user_preference", "default_user", "日维度")
    assert len(result.memories) == 1
    assert result.memories[0].content == "以后能耗分析默认按日维度展示"


@pytest.mark.parametrize(
    "user_input",
    [
        "我现在有几个偏好？",
        "请记住今天光伏发电量是 404 kWh",
        "默认展示当前 SOC 为 20%",
    ],
)
def test_legacy_keyword_rule_rejects_queries_and_retrievable_data(monkeypatch, user_input):
    """关键词 fallback 不保存疑问句或可查询运行数据。"""
    settings.memory.auto_extract_enabled = False
    monkeypatch.setattr(
        nodes,
        "extract_memories_from_turn",
        lambda **_: (_ for _ in ()).throw(AssertionError("extractor should not be called")),
    )

    update = nodes.memory_manager_node(_state(user_input))

    assert update == {}
    assert _search("user_preference", "default_user").memories == []


def test_duplicate_candidate_is_not_written_twice(monkeypatch):
    """完全重复正文不重复写入。"""
    _patch_extractor(
        monkeypatch,
        [_candidate("江北工厂冬季生产线不使用工艺冷却。", "site_fact")],
    )

    nodes.memory_manager_node(_state("请记住，江北工厂冬季生产线不使用工艺冷却"))
    update = nodes.memory_manager_node(
        _state("请记住，江北工厂冬季生产线不使用工艺冷却")
    )

    result = _search("site", "FJJB000001", "工艺冷却")
    assert len(result.memories) == 1
    assert update["memory_feedback"].startswith("已保存长期记忆")


def test_duplicate_user_preference_returns_success_feedback(monkeypatch):
    """重复保存同一偏好属于幂等成功，不误报为准入拒绝。"""
    _patch_extractor(
        monkeypatch,
        [_candidate("用户偏好：分析报告先给结论。", "user_preference")],
    )
    nodes.memory_manager_node(_state())

    update = nodes.memory_manager_node(_state())

    assert update["memory_write_result"].memory is not None
    assert update["memory_feedback"] == "已保存长期偏好：用户偏好：分析报告先给结论。"


def test_same_preference_key_updates_existing_memory(monkeypatch):
    """同一偏好键的新表述覆盖旧值，而不是新增冲突记录。"""
    _patch_extractor(
        monkeypatch,
        [
            _candidate(
                "用户偏好：能耗分析先给结论，再给数据依据。",
                "user_preference",
                memory_key="energy_analysis_report_order",
            )
        ],
    )
    nodes.memory_manager_node(_state("以后能耗分析先给结论，再给数据依据"))

    _patch_extractor(
        monkeypatch,
        [
            _candidate(
                "用户偏好：能耗分析先展示数据依据，最后给结论。",
                "user_preference",
                memory_key="energy_analysis_report_order",
            )
        ],
    )
    update = nodes.memory_manager_node(
        _state("请更新偏好：以后能耗分析先展示数据依据，最后给结论")
    )

    result = _search("user_preference", "default_user")
    assert len(result.memories) == 1
    assert result.memories[0].content == "用户偏好：能耗分析先展示数据依据，最后给结论。"
    assert update["memory_feedback"] == "已更新长期偏好：用户偏好：能耗分析先展示数据依据，最后给结论。"
    assert update["final_report"] == update["memory_feedback"]


def test_main_agent_does_not_bind_save_memory_tool():
    """主 Agent 不得直接绑定普通 save_memory，偏好统一由 memory_manager 写入。"""
    tool_names = {schema["name"] for schema in nodes._get_agent_tool_schemas()}
    assert "save_memory" not in tool_names
