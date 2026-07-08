"""test_harness_regression — 验证 main 新增安全护栏、跳转兜底与范围重试

所属层：tests
依赖：pytest, src.config.settings, src.graph.nodes, src.tools.java_backend
对接算法层：福加运营数据 REST API（Mock）
"""
import importlib

from src.config.settings import settings
from src.graph.nodes import _strip_redirect_if_no_jump
from src.tools import java_backend


hvac_rag = importlib.import_module("src.tools.query_hvac_knowledge")


def test_main_graph_prompt_contains_security_guardrails() -> None:
    """主图 Prompt 必须包含域外拒答、秘密保护、命令拒绝和不确定性约束。"""
    prompt = settings.prompts["cognitive_parser"]["system"]

    assert "域外拒答" in prompt
    assert "禁止泄露系统信息" in prompt
    assert "禁止执行命令" in prompt
    assert "不确定" in prompt


def test_redirect_phrase_removed_without_action_and_kept_with_action() -> None:
    """无 UIAction 时删除固定跳转话术，有 action 时必须保留。"""
    report = "冷水机组 COP 偏低时应检查冷却水温。\n\n详细信息请点击下方链接跳转。"

    assert "跳转" not in _strip_redirect_if_no_jump(report, {"pending_actions": []})
    assert "详细信息请点击下方链接跳转。" in _strip_redirect_if_no_jump(
        report, {"pending_actions": [{"route": "/analysis/cop"}]}
    )


def test_energy_range_retries_transient_daily_failure(monkeypatch) -> None:
    """单日瞬时失败应重试，并在第三次成功后纳入真实结果。"""
    calls = 0

    def fetch_summary(site_id: str, date: str) -> dict:
        nonlocal calls
        calls += 1
        if calls < 3:
            return {"error": "temporary"}
        return {"site_id": site_id, "date": date, "energy_kwh": 123.4}

    monkeypatch.setattr(java_backend, "_is_mock", lambda: False)
    monkeypatch.setattr(java_backend, "fetch_energy_summary", fetch_summary)
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    result = java_backend.fetch_energy_range("site_demo", "2026-07-01", "2026-07-01")

    assert calls == 3
    assert result["total_days"] == 1
    assert result["items"][0]["energy_kwh"] == 123.4
    assert "skipped_days" not in result


def test_energy_range_exposes_day_after_three_failures(monkeypatch) -> None:
    """三次失败后必须返回 skipped_days/hint，不能静默伪装完整数据。"""
    calls = 0

    def always_fail(_site_id: str, _date: str) -> dict:
        nonlocal calls
        calls += 1
        return {"error": "backend unavailable"}

    monkeypatch.setattr(java_backend, "_is_mock", lambda: False)
    monkeypatch.setattr(java_backend, "fetch_energy_summary", always_fail)
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    result = java_backend.fetch_energy_range("site_demo", "2026-07-02", "2026-07-02")

    assert calls == 3
    assert result["total_days"] == 0
    assert result["skipped_days"] == ["2026-07-02"]
    assert "3次重试" in result["skipped_hint"]


def test_hvac_embedding_uses_local_cache_and_reuses_instance(monkeypatch) -> None:
    """HVAC embedding 必须离线加载并在进程内复用，避免每次联网检查。"""
    created: list[dict] = []

    class FakeEmbeddingFunction:
        def __init__(self, **kwargs) -> None:
            created.append(kwargs)

    monkeypatch.setattr(
        "chromadb.utils.embedding_functions.SentenceTransformerEmbeddingFunction",
        FakeEmbeddingFunction,
    )
    hvac_rag._get_embedding_function.cache_clear()

    first = hvac_rag._get_embedding_function(True)
    second = hvac_rag._get_embedding_function(True)

    assert first is second
    assert created == [{
        "model_name": "BAAI/bge-small-zh-v1.5",
        "local_files_only": True,
    }]
    hvac_rag._get_embedding_function.cache_clear()
