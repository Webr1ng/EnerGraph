"""test_eval_adapters — 验证 Eval T2 配置、Fixture 与 Adapter 边界

所属层：tests
依赖：pytest, benchmarks.adapters, benchmarks.fixtures
对接算法层：N/A
"""
from pathlib import Path
import time

import pytest
from pydantic import ValidationError

from benchmarks.adapters import ApiAdapter, GraphAdapter, create_energraph_executor
from benchmarks.adapters.base import AdapterResponse, AdapterTimeoutError
from benchmarks.fixtures import FixtureRepository
from benchmarks.shared.case_loader import load_cases
from benchmarks.shared.config_models import EvalRunConfig, config_summary, load_run_config


ROOT = Path(__file__).resolve().parents[2]
CONFIGS = ROOT / "benchmarks" / "configs"
FIXTURES = ROOT / "benchmarks" / "fixtures" / "scripted_responses.json"
EXAMPLES = ROOT / "benchmarks" / "datasets" / "_examples"


def test_fast_and_standard_configs_load_with_expected_boundaries() -> None:
    """Fast 必须完全离线，Standard 可用真实 LLM 但保持 Mock Tool。"""
    fast = load_run_config(CONFIGS / "fast.yaml")
    standard = load_run_config(CONFIGS / "standard.yaml")

    assert (fast.network_allowed, fast.store.kind, fast.llm.kind, fast.tools.kind) == (
        False, "inmemory", "mock", "mock"
    )
    assert (standard.store.kind, standard.llm.kind, standard.tools.kind) == (
        "inmemory", "real", "mock"
    )


def test_fast_config_rejects_network_or_real_backend() -> None:
    """Fast 配置不得通过网络或真实后端绕过确定性边界。"""
    with pytest.raises(ValidationError, match="Fast 模式禁止网络访问"):
        EvalRunConfig(
            mode="fast", network_allowed=True,
            store={"kind": "inmemory"}, llm={"kind": "mock"}, tools={"kind": "mock"},
        )


def test_production_missing_dependencies_fails_fast() -> None:
    """Production 缺真实依赖配置时必须启动前失败，不能静默降级。"""
    with pytest.raises(ValueError, match="LOCAL_BASE_URL.*MEMORY_POSTGRES_DSN"):
        load_run_config(CONFIGS / "production.yaml", environment={})


def test_production_config_accepts_complete_dependency_map() -> None:
    """Production 依赖齐全时应通过预检，摘要不得包含环境变量值。"""
    environment = {
        "LOCAL_BASE_URL": "http://model.invalid/v1",
        "LOCAL_MODEL": "model-id",
        "MEMORY_POSTGRES_DSN": "postgresql://user:password@db.invalid/eval",
        "FUCA_API_BASE_URL": "https://api.invalid",
    }
    config = load_run_config(CONFIGS / "production.yaml", environment=environment)
    summary = config_summary(config)
    assert summary["mode"] == "production"
    assert "password" not in str(summary)


def test_fault_recovery_production_requires_explicit_safety_flag() -> None:
    """T14 Production 故障验收必须显式开启，避免误打真实生产依赖。"""
    environment = {
        "LOCAL_BASE_URL": "http://model.invalid/v1",
        "LOCAL_MODEL": "model-id",
        "MEMORY_POSTGRES_DSN": "postgresql://user:password@db.invalid/eval",
        "FUCA_API_BASE_URL": "https://api.invalid",
        "FUCA_TENANT_ID": "tenant",
        "EVAL_NAMESPACE_PREFIX": "eval_fault_isolated",
    }

    with pytest.raises(ValueError, match="EVAL_FAULT_RECOVERY_PRODUCTION"):
        load_run_config(CONFIGS / "fault_recovery_production.yaml", environment=environment)


def test_memory_postgres_config_requires_dsn() -> None:
    """Memory PostgreSQL 发布集缺 DSN 时必须在运行前失败。"""
    with pytest.raises(ValueError, match="Standard 缺少必需环境变量: MEMORY_POSTGRES_DSN"):
        load_run_config(CONFIGS / "memory_postgres.yaml", environment={})


def test_same_case_runs_through_fast_and_standard_graph_adapter() -> None:
    """同一 Case 应能在 Fast 与 Standard Adapter 边界得到统一响应契约。"""
    case = load_cases(EXAMPLES / "minimal_valid.jsonl")[0]
    repository = FixtureRepository.from_json(FIXTURES)

    fast_response = GraphAdapter(load_run_config(CONFIGS / "fast.yaml"), repository.execute).run(case)
    standard_response = GraphAdapter(
        load_run_config(CONFIGS / "standard.yaml"), repository.execute
    ).run(case)

    assert fast_response == standard_response
    assert fast_response.answer.startswith("我是青山大模型")


def test_namespace_is_cleaned_before_and_after_failure() -> None:
    """案例执行失败也必须清理独立 namespace，避免跨案例污染。"""
    case = load_cases(EXAMPLES / "minimal_valid.jsonl")[0]
    cleaned: list[str] = []

    def fail(*_args) -> None:
        raise RuntimeError("fixture failure")

    adapter = GraphAdapter(
        load_run_config(CONFIGS / "fast.yaml"), fail, namespace_cleaner=cleaned.append
    )
    with pytest.raises(RuntimeError, match="fixture failure"):
        adapter.run(case)

    assert cleaned == [adapter.case_namespace(case), adapter.case_namespace(case)]


def test_api_adapter_refuses_fast_network_access() -> None:
    """Fast 模式即使注入 transport 也不得执行 API 请求。"""
    case = load_cases(EXAMPLES / "minimal_valid.jsonl")[0]
    called = False

    def transport(*_args):
        nonlocal called
        called = True
        return {}

    adapter = ApiAdapter(load_run_config(CONFIGS / "fast.yaml"), transport)
    with pytest.raises(RuntimeError, match="禁止 API 网络访问"):
        adapter.run(case)
    assert called is False


def test_real_graph_executor_maps_state_to_adapter_response() -> None:
    """真实图执行器边界应提取回答、意图、Tool 调用和 token 用量。"""
    class Message:
        tool_calls = [{"name": "fetch_energy_range", "args": {"site_id": "site_demo"}}]
        usage_metadata = {"input_tokens": 12, "output_tokens": 4}

    class Intent:
        category = "energy"

    class FakeGraph:
        def invoke(self, initial_state, config):
            assert initial_state["thread_id"].startswith("eval_standard/graph/")
            assert config["configurable"]["thread_id"] == initial_state["thread_id"]
            return {
                "intent_plan": [Intent()],
                "messages": [Message()],
                "final_report": "查询完成",
                "error": None,
            }

    case = load_cases(EXAMPLES / "minimal_valid.jsonl")[0]
    adapter = GraphAdapter(
        load_run_config(CONFIGS / "standard.yaml"),
        create_energraph_executor(FakeGraph()),
    )
    response: AdapterResponse = adapter.run(case)

    assert response.actual_intents == ["monitor_query"]
    assert response.actual_agent == "ui_router"
    assert response.actual_skill == "ui_router"
    assert response.tool_calls[0].name == "fetch_energy_range"
    assert (response.input_tokens, response.output_tokens) == (12, 4)


def test_real_graph_executor_answer_fallback_skips_system_and_user_messages() -> None:
    """final_report 为空时，报告兜底只能使用 assistant 文本，不能泄露 system prompt。"""
    class Message:
        def __init__(self, content: str, message_type: str) -> None:
            self.content = content
            self.type = message_type
            self.tool_calls = []
            self.usage_metadata = {}

    class FakeGraph:
        def invoke(self, _initial_state, config=None):
            return {
                "messages": [
                    Message("system secret prompt", "system"),
                    Message("用户问题", "human"),
                    Message("请告诉我您想查看的站点 ID。", "ai"),
                ],
                "final_report": "",
                "error": None,
            }

    case = load_cases(EXAMPLES / "minimal_valid.jsonl")[0]
    adapter = GraphAdapter(
        load_run_config(CONFIGS / "standard.yaml"),
        create_energraph_executor(FakeGraph()),
    )

    response = adapter.run(case)

    assert response.answer == "请告诉我您想查看的站点 ID。"
    assert "system secret" not in response.answer


def test_real_graph_executor_answer_fallback_uses_last_assistant_message() -> None:
    """final_report 为空且有多轮 assistant 文本时，应取最后一条更接近最终回答。"""
    class Message:
        def __init__(self, content: str) -> None:
            self.content = content
            self.type = "ai"
            self.tool_calls = []
            self.usage_metadata = {}

    class FakeGraph:
        def invoke(self, _initial_state, config=None):
            return {
                "messages": [
                    Message("中间分析：准备查询数据。"),
                    Message("最终回答：已完成查询。"),
                ],
                "final_report": "",
                "error": None,
            }

    case = load_cases(EXAMPLES / "minimal_valid.jsonl")[0]
    adapter = GraphAdapter(
        load_run_config(CONFIGS / "standard.yaml"),
        create_energraph_executor(FakeGraph()),
    )

    response = adapter.run(case)

    assert response.answer == "最终回答：已完成查询。"


def test_standard_graph_executor_disables_memory_persistence(monkeypatch) -> None:
    """Standard InMemory 配置应压过本地 .env 的 PostgreSQL 记忆开关。"""
    from src.config.settings import settings

    monkeypatch.setattr(settings.memory, "enabled", True)
    monkeypatch.setattr(settings.memory, "use_postgres_store", True)
    monkeypatch.setattr(settings.memory, "demo_file_store_enabled", True)
    monkeypatch.setattr(settings.memory, "auto_extract_enabled", True)

    class FakeGraph:
        def invoke(self, _initial_state, config=None):
            assert settings.memory.enabled is False
            assert settings.memory.use_postgres_store is False
            assert settings.memory.demo_file_store_enabled is False
            assert settings.memory.auto_extract_enabled is False
            return {"messages": [], "final_report": "ok", "error": None}

    case = load_cases(EXAMPLES / "minimal_valid.jsonl")[0]
    adapter = GraphAdapter(
        load_run_config(CONFIGS / "standard.yaml"),
        create_energraph_executor(FakeGraph()),
    )

    assert adapter.run(case).answer == "ok"


def test_standard_graph_executor_uses_mock_tools(monkeypatch) -> None:
    """Standard 声明 tools=mock 时，真实 Graph 内部也不得触达产品 Tool。"""
    from src.tools import TOOL_REGISTRY

    def forbidden_real_tool(**_arguments):
        raise AssertionError("real product tool should not execute in Standard mock-tools mode")

    monkeypatch.setitem(TOOL_REGISTRY, "fetch_energy_summary", forbidden_real_tool)

    class FakeGraph:
        def invoke(self, initial_state, config=None):
            result = TOOL_REGISTRY["fetch_energy_summary"](site_id=initial_state["site_id"])
            assert result["mock"] is True
            assert result["tool"] == "fetch_energy_summary"
            assert result["site_id"] == initial_state["site_id"]
            return {"messages": [], "final_report": "mock tool ok", "error": None}

    case = load_cases(EXAMPLES / "minimal_valid.jsonl")[0]
    adapter = GraphAdapter(
        load_run_config(CONFIGS / "standard.yaml"),
        create_energraph_executor(FakeGraph()),
    )

    assert adapter.run(case).answer == "mock tool ok"
    assert TOOL_REGISTRY["fetch_energy_summary"] is forbidden_real_tool


def test_adapter_enforces_timeout_budget() -> None:
    """阻塞执行超过预算时必须中断并报告 case_id。"""
    case = load_cases(EXAMPLES / "minimal_valid.jsonl")[0]
    config = load_run_config(CONFIGS / "fast.yaml")
    config.options.timeout_seconds = 0.02

    def blocked(*_args):
        time.sleep(0.2)
        return AdapterResponse()

    with pytest.raises(AdapterTimeoutError, match="routing_greeting_001"):
        GraphAdapter(config, blocked).run(case)


def test_adapter_retries_transient_failure_within_limit() -> None:
    """瞬时异常应按配置有限重试，成功后返回统一响应。"""
    case = load_cases(EXAMPLES / "minimal_valid.jsonl")[0]
    config = load_run_config(CONFIGS / "fast.yaml")
    config.options.retries = 1
    calls = 0

    def flaky(*_args):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("transient")
        return AdapterResponse(answer="ok")

    assert GraphAdapter(config, flaky).run(case).answer == "ok"
    assert calls == 2
