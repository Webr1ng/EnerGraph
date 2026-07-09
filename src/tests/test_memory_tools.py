"""test_memory_tools — search_memory/save_memory 工具测试

所属层：tests
依赖：importlib, pathlib, pytest
对接算法层：N/A
"""
import importlib.util
from pathlib import Path

import pytest

from src.config.settings import settings
from src.memory.store import reset_memory_store


def _load_memory_ops():
    """绕过 src.tools.__init__ 加载 memory_ops，避免无 LangChain 环境下测试失败。"""
    module_path = Path(__file__).resolve().parents[1] / "tools" / "memory_ops.py"
    spec = importlib.util.spec_from_file_location("memory_ops_under_test", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


_MEMORY_OPS = _load_memory_ops()
delete_memory = _MEMORY_OPS.delete_memory
save_memory = _MEMORY_OPS.save_memory
search_memory = _MEMORY_OPS.search_memory
search_relevant_memory = _MEMORY_OPS.search_relevant_memory


@pytest.fixture(autouse=True)
def clean_memory_store():
    """每个用例清空内存 store。"""
    original_demo_enabled = settings.memory.demo_file_store_enabled
    settings.memory.demo_file_store_enabled = False
    reset_memory_store()
    yield
    settings.memory.demo_file_store_enabled = original_demo_enabled
    reset_memory_store()


def test_save_memory_tool_success():
    """save_memory 正常写入并返回 Pydantic 输出结构的 dict。"""
    result = save_memory(
        content="用户偏好报告先给结论，再给数据依据",
        agent_id="main_graph",
        site_id="FJJB000001",
        memory_key="energy_analysis_report_order",
        metadata={
            "memory_type": "user_preference",
            "source_thread_id": "thread-1",
            "confidence": 0.85,
            "tags": ["report_style"],
        },
    )

    assert "error" not in result
    assert result["memory"]["content"] == "用户偏好报告先给结论，再给数据依据"
    assert result["namespace"][:4] == ["energraph", "dev", "FJJB000001", "main_graph"]
    assert result["namespace"][-2:] == ["user_preference", "default_user"]


def test_save_memory_user_preference_requires_memory_key():
    """普通 save_memory 不允许无 key 新增用户偏好。"""
    result = save_memory(
        content="用户偏好报告先给结论",
        site_id="FJJB000001",
        metadata={"memory_type": "user_preference"},
    )

    assert result["error"] == "memory: user_preference requires memory_key"


def test_save_memory_user_preference_upserts_by_key():
    """管理端显式写偏好时也统一按 memory_key 原地更新。"""
    first = save_memory(
        content="用户偏好：先给结论，再给数据。",
        site_id="FJJB000001",
        memory_key="energy_analysis_report_order",
        metadata={"memory_type": "user_preference"},
    )
    second = save_memory(
        content="用户偏好：先给数据，最后给结论。",
        site_id="FJJB000001",
        memory_key="energy_analysis_report_order",
        metadata={"memory_type": "user_preference"},
    )

    result = search_memory(
        site_id="FJJB000001",
        scope="user_preference",
        entity_id="default_user",
    )
    assert first["memory"]["id"] == second["memory"]["id"]
    assert len(result["memories"]) == 1
    assert result["memories"][0]["content"] == "用户偏好：先给数据，最后给结论。"


def test_search_memory_tool_success():
    """search_memory 能检索同 namespace 下的记忆。"""
    save_memory(
        content="江北工厂默认站点为 FJJB000001",
        agent_id="main_graph",
        site_id="FJJB000001",
        metadata={
            "memory_type": "site_fact",
            "source_thread_id": "thread-1",
            "confidence": 0.9,
            "tags": ["site"],
        },
    )

    result = search_memory(
        query="江北工厂",
        agent_id="main_graph",
        site_id="FJJB000001",
    )

    assert "error" not in result
    assert len(result["memories"]) == 1
    assert result["memories"][0]["metadata"]["memory_type"] == "site_fact"


def test_save_memory_tool_invalid_temporary_memory():
    """临时记忆缺少 TTL 时返回 error，不抛出异常。"""
    result = save_memory(
        content="当前报警：冷却塔温度偏高",
        agent_id="main_graph",
        site_id="FJJB000001",
        metadata={
            "memory_type": "device_state",
            "source_thread_id": "thread-1",
        },
    )

    assert result["error"].startswith("memory:")


def test_search_memory_tool_limit_validation():
    """非法 limit 返回 error，不抛出异常。"""
    result = search_memory(limit=0)

    assert result["error"].startswith("memory:")


def test_delete_memory_tool_success_and_idempotent():
    """delete_memory 删除指定 namespace 下的记忆，并且重复删除安全返回 false。"""
    saved = save_memory(
        content="用户偏好报告先给结论。",
        site_id="FJJB000001",
        scope="session_note",
        entity_id="thread-delete",
        metadata={
            "memory_type": "session_note",
            "source_thread_id": "thread-delete",
        },
    )
    memory_id = saved["memory"]["id"]

    deleted = delete_memory(
        memory_id=memory_id,
        site_id="FJJB000001",
        scope="session_note",
        entity_id="thread-delete",
    )
    search_result = search_memory(
        site_id="FJJB000001",
        scope="session_note",
        entity_id="thread-delete",
    )
    repeated = delete_memory(
        memory_id=memory_id,
        site_id="FJJB000001",
        scope="session_note",
        entity_id="thread-delete",
    )

    assert "error" not in deleted
    assert deleted["deleted"] is True
    assert search_result["memories"] == []
    assert repeated["deleted"] is False


def test_delete_memory_tool_invalid_memory_id():
    """非法 memory_id 返回 error，不抛出异常。"""
    result = delete_memory(memory_id="")

    assert result["error"].startswith("memory:")


def test_search_relevant_memory_tool_aggregates_scopes():
    """search_relevant_memory 跨常用 scope 聚合检索。"""
    save_memory(
        content="江北工厂有一台磁悬浮主机。",
        agent_id="main_graph",
        site_id="FJJB000001",
        scope="site",
        entity_id="FJJB000001",
        metadata={
            "memory_type": "site_fact",
            "source_thread_id": "thread-1",
            "confidence": 0.9,
        },
    )
    save_memory(
        content="储能 SOC 不得低于 20%。",
        agent_id="main_graph",
        site_id="FJJB000001",
        scope="safety_constraint",
        entity_id="FJJB000001",
        metadata={
            "memory_type": "safety_constraint",
            "source_thread_id": "thread-1",
            "confidence": 0.9,
        },
    )

    result = search_relevant_memory(
        query="江北工厂有哪些长期信息和运行约束",
        agent_id="main_graph",
        site_id="FJJB000001",
        thread_id="thread-1",
    )

    contents = [item["content"] for item in result["memories"]]
    assert "江北工厂有一台磁悬浮主机。" in contents
    assert "储能 SOC 不得低于 20%。" in contents
