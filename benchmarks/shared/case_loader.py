"""case_loader — Eval JSONL 加载、唯一性校验、脱敏与确定性序列化

所属层：tests
依赖：json, pydantic, benchmarks.shared.result_models
对接算法层：N/A
"""
import json
import re
from pathlib import Path
from typing import Any, Iterable, List

from pydantic import ValidationError

from benchmarks.shared.result_models import EvalCase


_SENSITIVE_KEY = re.compile(
    r"(?:^|[_-])(?:api[_-]?(?:key|token)|access[_-]?token|refresh[_-]?token|auth[_-]?token|token|password|authorization|secret|postgres(?:ql)?[_-]?dsn)(?:$|[_-])",
    re.IGNORECASE,
)
_SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"(?i)bearer\s+[a-z0-9._~+/=-]+"),
    re.compile(r"(?i)postgres(?:ql)?://[^\s/@:]+:[^\s/@]+@[^\s]+"),
)
REDACTED = "[REDACTED]"


def load_cases(path: Path | str) -> List[EvalCase]:
    """从 JSONL 文件加载用例并校验 case_id 唯一。

    Args:
        path: JSONL 文件路径。

    Returns:
        按文件顺序返回的已验证用例。

    Raises:
        ValueError: JSON、Schema 非法，文件为空或 case_id 重复。
        OSError: 文件不可读取。
    """
    resolved = Path(path)
    cases: List[EvalCase] = []
    seen: set[str] = set()
    for line_number, raw_line in enumerate(resolved.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{resolved}:{line_number}: 非法 JSON: {exc.msg}") from exc
        try:
            case = EvalCase.model_validate(payload)
        except ValidationError as exc:
            raise ValueError(f"{resolved}:{line_number}: 用例 Schema 校验失败: {exc}") from exc
        if case.case_id in seen:
            raise ValueError(f"{resolved}:{line_number}: case_id 重复: {case.case_id}")
        seen.add(case.case_id)
        cases.append(case)
    if not cases:
        raise ValueError(f"{resolved}: 未找到有效用例")
    return cases


def sanitize_sensitive(value: Any) -> Any:
    """递归脱敏配置、证据和报告对象中的密钥及凭据。

    Args:
        value: 任意 JSON-compatible 对象或 Pydantic 模型。

    Returns:
        保持原结构的脱敏副本。
    """
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if isinstance(value, dict):
        return {
            str(key): REDACTED if _SENSITIVE_KEY.search(str(key)) else sanitize_sensitive(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [sanitize_sensitive(item) for item in value]
    if isinstance(value, str):
        result = value
        for pattern in _SENSITIVE_VALUE_PATTERNS:
            result = pattern.sub(REDACTED, result)
        return result
    return value


def deterministic_json(value: Any) -> str:
    """将对象脱敏后序列化为稳定、可比较的 JSON。

    Args:
        value: 任意 JSON-compatible 对象或 Pydantic 模型。

    Returns:
        key 排序且格式固定的 UTF-8 JSON 字符串。
    """
    return json.dumps(
        sanitize_sensitive(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def write_jsonl(path: Path | str, values: Iterable[Any]) -> None:
    """以确定性、脱敏格式写入 JSONL 文件。

    Args:
        path: 输出文件路径。
        values: 待序列化对象序列。

    Returns:
        None。
    """
    resolved = Path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    lines = [deterministic_json(value) for value in values]
    resolved.write_text("\n".join(lines) + "\n", encoding="utf-8")
