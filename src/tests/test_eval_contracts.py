"""test_eval_contracts — 验证 EnerGraph Eval v0.1 共用契约与加载器

所属层：tests
依赖：pytest, pydantic, benchmarks.shared
对接算法层：N/A
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from benchmarks.shared.case_loader import (
    REDACTED,
    deterministic_json,
    load_cases,
    sanitize_sensitive,
    write_jsonl,
)
from benchmarks.shared.result_models import (
    EvalCase,
    EvalExpected,
    EvalResult,
    GateResult,
    RunManifest,
)


EXAMPLES = Path(__file__).resolve().parents[2] / "benchmarks" / "datasets" / "_examples"


def test_load_minimal_and_multi_turn_examples() -> None:
    """合法的最小与多轮样例应按 v0.1 契约加载。"""
    minimal = load_cases(EXAMPLES / "minimal_valid.jsonl")
    multi_turn = load_cases(EXAMPLES / "multi_turn_valid.jsonl")

    assert minimal[0].case_id == "routing_greeting_001"
    assert multi_turn[0].turns[-1].content == "再导出成表格"
    assert multi_turn[0].expected.required_tools == ["export_data_table"]


def test_unknown_version_reports_file_and_line() -> None:
    """未知 Schema 版本必须快速失败并指出文件行号。"""
    with pytest.raises(ValueError, match=r"invalid_unknown_version\.jsonl:1:.*Schema"):
        load_cases(EXAMPLES / "invalid_unknown_version.jsonl")


def test_duplicate_case_id_is_rejected(tmp_path: Path) -> None:
    """同一数据集内重复 case_id 必须被拒绝。"""
    line = (EXAMPLES / "minimal_valid.jsonl").read_text(encoding="utf-8").strip()
    duplicate = tmp_path / "duplicate.jsonl"
    duplicate.write_text(f"{line}\n{line}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="case_id 重复: routing_greeting_001"):
        load_cases(duplicate)


def test_invalid_case_id_and_overlapping_tool_sets_are_rejected() -> None:
    """非法 ID 及互相冲突的工具期望必须在建模阶段失败。"""
    payload = json.loads((EXAMPLES / "minimal_valid.jsonl").read_text(encoding="utf-8"))
    payload["case_id"] = "BAD"
    with pytest.raises(ValidationError):
        EvalCase.model_validate(payload)

    with pytest.raises(ValidationError, match="存在重复工具"):
        EvalExpected(required_tools=["fetch_energy_range"], forbidden_tools=["fetch_energy_range"])


def test_sensitive_data_is_redacted_recursively() -> None:
    """密钥字段、Bearer Token 与带密码 DSN 均不得进入报告。"""
    raw = {
        "api_key": "secret-value",
        "input_tokens": 123,
        "output_tokens": 45,
        "nested": {
            "message": "Authorization: Bearer abc.def-123",
            "dsn": "postgresql://energraph:password@localhost:5432/energraph",
        },
    }
    sanitized = sanitize_sensitive(raw)

    assert sanitized["api_key"] == REDACTED
    assert sanitized["input_tokens"] == 123
    assert sanitized["output_tokens"] == 45
    assert "abc.def-123" not in sanitized["nested"]["message"]
    assert "password" not in sanitized["nested"]["dsn"]


def test_deterministic_serialization_and_jsonl_write(tmp_path: Path) -> None:
    """序列化必须稳定排序，JSONL 写入必须可重新加载。"""
    assert deterministic_json({"b": 2, "a": 1}) == '{"a":1,"b":2}'
    cases = load_cases(EXAMPLES / "minimal_valid.jsonl")
    output = tmp_path / "cases.jsonl"
    write_jsonl(output, cases)
    assert load_cases(output) == cases


def test_result_gate_and_manifest_contracts() -> None:
    """结果硬门禁聚合与运行清单必填版本信息应有效。"""
    result = EvalResult(
        run_id="run-001",
        case_id="routing_greeting_001",
        mode="standard",
        model_id="qwen3.6-35b-a3b",
        prompt_version="git:abc123",
        code_version="abc123",
        gates=[GateResult(name="unsupported_numeric_claim", violated=False)],
        latency_ms=100,
    )
    assert result.hard_gate_passed is True

    manifest = RunManifest(
        run_id="run-001",
        mode="standard",
        git_commit="abc123",
        git_dirty=True,
        dataset_versions={"routing": "0.1"},
        threshold_version="0.1",
        model_id="qwen3.6-35b-a3b",
        prompt_version="git:abc123",
        started_at=datetime.now(timezone.utc),
        random_seed=42,
    )
    assert manifest.model_id == "qwen3.6-35b-a3b"
