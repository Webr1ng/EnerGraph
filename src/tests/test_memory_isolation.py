"""test_memory_isolation — 多环境/站点/Agent 记忆隔离测试

所属层：tests
依赖：importlib, pathlib, pytest, src.memory.store
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
    spec = importlib.util.spec_from_file_location("memory_ops_under_test_isolation", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


_MEMORY_OPS = _load_memory_ops()
save_memory = _MEMORY_OPS.save_memory
search_memory = _MEMORY_OPS.search_memory


@pytest.fixture(autouse=True)
def clean_memory_store():
    """每个用例清空内存 store。"""
    reset_memory_store()
    original_env = settings.memory.env
    yield
    settings.memory.env = original_env
    reset_memory_store()


def _save(content: str, agent_id: str, site_id: str) -> None:
    """写入测试记忆。"""
    save_memory(
        content=content,
        agent_id=agent_id,
        site_id=site_id,
        metadata={
            "memory_type": "site_fact",
            "source_thread_id": "thread-1",
            "confidence": 0.9,
        },
    )


def test_agent_namespace_isolation():
    """HVAC 写入的记忆不会被 PowerAI 默认检索到。"""
    _save("HVAC 偏好：回答先引用暖通规范", "hvac_expert", "FJJB000001")

    hvac_result = search_memory(
        query="暖通规范",
        agent_id="hvac_expert",
        site_id="FJJB000001",
    )
    powerai_result = search_memory(
        query="暖通规范",
        agent_id="powerai",
        site_id="FJJB000001",
    )

    assert len(hvac_result["memories"]) == 1
    assert powerai_result["memories"] == []


def test_site_namespace_isolation():
    """不同 site_id 默认不互通。"""
    _save("江北工厂默认站点为 FJJB000001", "main_graph", "FJJB000001")

    same_site = search_memory(query="江北工厂", agent_id="main_graph", site_id="FJJB000001")
    other_site = search_memory(query="江北工厂", agent_id="main_graph", site_id="OTHER_SITE")

    assert len(same_site["memories"]) == 1
    assert other_site["memories"] == []


def test_env_namespace_isolation():
    """dev/prod namespace 默认不互通。"""
    settings.memory.env = "dev"
    _save("生产策略必须人工确认后下发", "powerai", "FJJB000001")

    settings.memory.env = "prod"
    prod_result = search_memory(query="人工确认", agent_id="powerai", site_id="FJJB000001")

    settings.memory.env = "dev"
    dev_result = search_memory(query="人工确认", agent_id="powerai", site_id="FJJB000001")

    assert prod_result["memories"] == []
    assert len(dev_result["memories"]) == 1


def test_base_agent_memory_namespace_default():
    """BaseAgent 默认 namespace 包含 prefix/env/site/agent。"""
    pytest.importorskip("langgraph")
    from src.graph.agents.base_agent import BaseAgent

    class DemoAgent(BaseAgent):
        """测试 Agent。"""

        @property
        def name(self) -> str:
            """Agent 名称。"""
            return "demo"

        @property
        def description(self) -> str:
            """Agent 描述。"""
            return "demo"

        @property
        def state_schema(self):
            """测试 state schema。"""
            return dict

        def build_graph(self):
            """测试不构图。"""
            return None

    namespace = DemoAgent().memory_namespace(site_id="FJJB000001", scope="site", entity_id="FJJB000001")

    assert namespace == ["energraph", settings.memory.env, "FJJB000001", "demo", "site", "FJJB000001"]
