"""test_memory_benchmark — 验证 Memory MiniBench 100-record Fast 集与硬门禁

所属层：tests
依赖：pytest, benchmarks.adapters, benchmarks.datasets.memory, benchmarks.scorers
对接算法层：N/A
"""
from pathlib import Path

import pytest

from benchmarks.adapters import (
    MemoryAdapter,
    create_memory_benchmark_executor,
    memory_namespace_cleaner,
)
from benchmarks.adapters.base import AdapterResponse
from benchmarks.datasets.memory.v0_1 import load_memory_cases
from benchmarks.runners.run_memory import main as run_memory_main
from benchmarks.runners.run_all import exit_code_for_results, run_cases
from benchmarks.scorers import MemoryScorer, ScorerRegistry
from benchmarks.shared.config_models import load_run_config
from benchmarks.shared.report_generator import aggregate_results
from benchmarks.shared.result_models import EvalCase
from src.config.settings import settings
from src.memory.store import reset_memory_store


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def clean_memory_settings():
    """强制 Memory MiniBench 使用 InMemory Store 并恢复配置。"""
    original = (
        settings.memory.enabled,
        settings.memory.use_postgres_store,
        settings.memory.demo_file_store_enabled,
        settings.memory.namespace_prefix,
        settings.memory.env,
        settings.memory.postgres_dsn,
    )
    settings.memory.enabled = False
    settings.memory.use_postgres_store = False
    settings.memory.demo_file_store_enabled = False
    settings.memory.namespace_prefix = "energraph"
    settings.memory.env = "dev"
    reset_memory_store()
    yield
    settings.memory.enabled = original[0]
    settings.memory.use_postgres_store = original[1]
    settings.memory.demo_file_store_enabled = original[2]
    settings.memory.namespace_prefix = original[3]
    settings.memory.env = original[4]
    settings.memory.postgres_dsn = original[5]
    reset_memory_store()


def _run_all_memory_cases():
    """执行完整 Memory Fast 集。"""
    config = load_run_config(ROOT / "benchmarks" / "configs" / "fast.yaml")
    adapter = MemoryAdapter(
        config, create_memory_benchmark_executor(),
        namespace_cleaner=memory_namespace_cleaner,
    )
    cases = load_memory_cases()
    results = run_cases(
        cases, adapter=adapter, scorers=ScorerRegistry([MemoryScorer()]),
        run_id="memory-test", model_id="deterministic-memory-store",
        code_version="test", prompt_version="test",
    )
    return cases, results


def test_memory_dataset_expands_to_100_unique_records() -> None:
    """10 个基础场景必须扩展为 100 条唯一 namespace 记录。"""
    cases = load_memory_cases()
    assert len(cases) == 100
    assert len({case.case_id for case in cases}) == 100
    contexts = {
        tuple(case.fixtures["memory_context"].values()) for case in cases
    }
    assert len(contexts) == 10


def test_memory_fast_suite_passes_all_metrics_and_gates() -> None:
    """真实 InMemory Store 的 100 条组合案例应全部通过。"""
    cases, results = _run_all_memory_cases()
    summary = aggregate_results(results)

    assert len(results) == len(cases) == 100
    assert exit_code_for_results(results) == 0
    assert summary["hard_gate_passed"] is True
    assert summary["failed_cases"] == []
    assert all(score == 1.0 for score in summary["metric_macro"].values())


def test_memory_fast_runner_overrides_local_postgres_env(tmp_path: Path) -> None:
    """Fast runner 必须覆盖本地 PostgreSQL 开关，避免 `.env` 污染离线门禁。"""
    settings.memory.use_postgres_store = True
    settings.memory.enabled = True
    settings.memory.postgres_dsn = "postgresql://user:password@localhost:5432/energraph"

    code = run_memory_main([
        "--config", str(ROOT / "benchmarks" / "configs" / "fast.yaml"),
        "--output-dir", str(tmp_path / "memory_fast"),
        "--case-id", "memory_write_preference_001_v01",
        "--run-id", "memory-fast-env-isolation",
    ])

    assert code == 0
    assert settings.memory.use_postgres_store is False


@pytest.mark.parametrize(
    ("field", "gate_name"),
    [
        ("leaked_aliases", "cross_namespace_memory_leakage"),
        ("stale_used_aliases", "stale_or_deleted_memory_use"),
        ("deleted_used_aliases", "stale_or_deleted_memory_use"),
        ("safety_constraint_violated", "memory_safety_constraint_violation"),
    ],
)
def test_memory_negative_observations_trigger_hard_gates(field: str, gate_name: str) -> None:
    """故意构造的泄漏、过期、删除和安全负例必须触发对应门禁。"""
    case = load_memory_cases()[0]
    value = True if field == "safety_constraint_violated" else ["forbidden"]
    response = AdapterResponse(observations={"memory": {field: value}})
    bundle = MemoryScorer().score(case, response)
    assert any(gate.name == gate_name and gate.violated for gate in bundle.gates)


def test_device_state_without_ttl_triggers_hard_gate() -> None:
    """设备状态无 TTL 写入必须触发零容忍门禁。"""
    case: EvalCase = load_memory_cases()[0]
    response = AdapterResponse(observations={"memory": {"writes": [{
        "memory_type": "device_state", "ttl_seconds": None, "valid_until": None,
    }]}})
    bundle = MemoryScorer().score(case, response)
    assert any(
        gate.name == "device_state_long_term_write" and gate.violated
        for gate in bundle.gates
    )
