"""test_memory_regression — T9 Memory P0 离线回归门禁

所属层：tests
依赖：pytest, benchmarks.adapters.memory_adapter, benchmarks.scorers.memory_scorer
对接算法层：N/A
"""
from pathlib import Path
from typing import Iterator

import pytest

from benchmarks.adapters import MemoryAdapter, create_memory_benchmark_executor, memory_namespace_cleaner
from benchmarks.datasets.memory.v0_1 import load_memory_cases
from benchmarks.scorers import MemoryScorer
from benchmarks.shared.config_models import load_run_config
from benchmarks.shared.result_models import EvalCase
from src.config.settings import settings
from src.memory.store import reset_memory_store


ROOT = Path(__file__).resolve().parents[2]
CASES = [case for case in load_memory_cases() if case.case_id.endswith("_v01")]


@pytest.fixture(autouse=True)
def force_inmemory_store() -> Iterator[None]:
    """强制使用 InMemory，避免开发机 `.env` 连接 PostgreSQL。"""
    original = (settings.memory.use_postgres_store, settings.memory.demo_file_store_enabled)
    settings.memory.use_postgres_store = False
    settings.memory.demo_file_store_enabled = False
    reset_memory_store()
    yield
    settings.memory.use_postgres_store, settings.memory.demo_file_store_enabled = original
    reset_memory_store()


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.case_id)
def test_memory_p0_regression(case: EvalCase) -> None:
    """每个 Memory 高风险基础场景必须保持指标全一且 gate 为零。"""
    config = load_run_config(ROOT / "benchmarks/configs/fast.yaml")
    response = MemoryAdapter(
        config, create_memory_benchmark_executor(), namespace_cleaner=memory_namespace_cleaner,
    ).run(case)
    bundle = MemoryScorer().score(case, response)
    assert not any(gate.violated for gate in bundle.gates), case.case_id
    assert all(metric.score == 1.0 for metric in bundle.metrics), case.case_id
