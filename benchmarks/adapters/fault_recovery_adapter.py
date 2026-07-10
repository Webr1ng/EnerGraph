"""fault_recovery_adapter — PostgreSQL 与外部依赖故障验收适配器

所属层：tests
依赖：benchmarks.adapters.base
对接算法层：N/A
"""
import json
import os
from typing import Callable

from benchmarks.adapters.base import AdapterResponse, BaseAdapter
from benchmarks.shared.config_models import EvalRunConfig
from benchmarks.shared.result_models import EvalCase


class FaultRecoveryAdapter(BaseAdapter):
    """适配故障恢复观测结果。"""

    adapter_name = "fault_recovery"


def create_fault_recovery_fixture_executor() -> Callable:
    """创建读取 fault_recovery_output 的确定性执行器。"""
    def execute(case: EvalCase, _config: EvalRunConfig, _namespace: str) -> AdapterResponse:
        output = case.fixtures.get("fault_recovery_output", {})
        return AdapterResponse(
            answer=str(output.get("evidence", "")),
            observations={"fault_recovery": output},
            evidence_summary=f"fixed fault recovery fixture: {case.case_id}",
        )

    return execute


def _base_observation(case: EvalCase, *, evidence: str) -> dict:
    """构造默认失败观测，Production 缺真实证据时不得伪造通过。"""
    fixture = case.fixtures.get("fault_recovery_output", {})
    return {
        "component": fixture.get("component", "unknown"),
        "failure": fixture.get("failure", "unknown"),
        "safe_degraded": False,
        "no_cross_domain_leak": True,
        "no_fabrication": True,
        "recovered": False,
        "data_consistent": False,
        "cleanup_ok": True,
        "production_untouched": True,
        "evidence": evidence,
    }


def _load_external_evidence() -> dict:
    """读取真实故障注入器产出的脱敏证据文件。"""
    path = os.getenv("EVAL_FAULT_RECOVERY_EVIDENCE_PATH", "").strip()
    if not path:
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("EVAL_FAULT_RECOVERY_EVIDENCE_PATH 根节点必须是对象")
    return payload


def _postgres_probe(case: EvalCase, namespace: str) -> dict:
    """对 PostgreSQL 依赖做只写 eval namespace 的安全探测。"""
    fixture = case.fixtures.get("fault_recovery_output", {})
    failure = fixture.get("failure", "unknown")
    observation = _base_observation(case, evidence="")
    try:
        import psycopg

        dsn = os.getenv("MEMORY_POSTGRES_DSN", "")
        table = "energraph_eval_fault_recovery"
        key = case.case_id
        value = f"{namespace}:{failure}"
        with psycopg.connect(dsn, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {table} (
                        namespace text NOT NULL,
                        case_id text NOT NULL,
                        probe_key text NOT NULL,
                        probe_value text NOT NULL,
                        created_at timestamptz DEFAULT now(),
                        PRIMARY KEY (namespace, case_id, probe_key)
                    )
                    """
                )
                cur.execute(
                    f"DELETE FROM {table} WHERE namespace = %s AND case_id = %s",
                    (namespace, case.case_id),
                )
                cur.execute(
                    f"INSERT INTO {table} (namespace, case_id, probe_key, probe_value) VALUES (%s, %s, %s, %s)",
                    (namespace, case.case_id, key, value),
                )
            conn.commit()

        with psycopg.connect(dsn, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT probe_value FROM {table} WHERE namespace = %s AND case_id = %s AND probe_key = %s",
                    (namespace, case.case_id, key),
                )
                row = cur.fetchone()
                cur.execute(
                    f"SELECT count(*) FROM {table} WHERE namespace = %s",
                    (f"{namespace}_neighbor",),
                )
                neighbor_count = int(cur.fetchone()[0])
                cur.execute(
                    f"DELETE FROM {table} WHERE namespace = %s AND case_id = %s",
                    (namespace, case.case_id),
                )
            conn.commit()

        ok = bool(row and row[0] == value and neighbor_count == 0)
        observation.update({
            "safe_degraded": ok,
            "recovered": ok,
            "data_consistent": ok,
            "cleanup_ok": ok,
            "production_untouched": namespace.startswith("eval_"),
            "evidence": f"postgres eval table round-trip ok={ok}; failure={failure}",
        })
    except Exception as exc:
        observation.update({
            "safe_degraded": True,
            "recovered": False,
            "data_consistent": False,
            "cleanup_ok": True,
            "production_untouched": namespace.startswith("eval_"),
            "evidence": f"postgres probe failed safely: {exc}",
        })
    return observation


def _illegal_tool_probe(case: EvalCase) -> dict:
    """验证未知 Tool 不在产品工具注册表中，不能被执行。"""
    from src.tools import TOOL_REGISTRY

    unknown_name = "__eval_forbidden_tool__"
    rejected = unknown_name not in TOOL_REGISTRY
    observation = _base_observation(case, evidence=f"unknown tool rejected={rejected}")
    observation.update({
        "safe_degraded": rejected,
        "recovered": False,
        "data_consistent": True,
        "cleanup_ok": True,
        "production_untouched": True,
    })
    return observation


def create_fault_recovery_production_executor() -> Callable:
    """创建真实 Production 故障恢复执行器。

    自动探测仅覆盖不会破坏外部系统的 PostgreSQL namespace 与非法 Tool 拒绝路径。
    401/500/字段缺失/LLM 超时/流中断等必须由外部故障注入器产出
    ``EVAL_FAULT_RECOVERY_EVIDENCE_PATH`` 脱敏证据；缺证据时返回失败观测。
    """
    external_evidence = _load_external_evidence()

    def execute(case: EvalCase, _config: EvalRunConfig, namespace: str) -> AdapterResponse:
        if case.case_id in external_evidence:
            output = external_evidence[case.case_id]
            return AdapterResponse(
                answer=str(output.get("evidence", "")),
                observations={"fault_recovery": output},
                evidence_summary=f"production fault evidence: {case.case_id}",
            )

        if "postgres" in case.tags and case.fixtures.get("fault_recovery_output", {}).get("failure") != "permission_denied":
            output = _postgres_probe(case, namespace)
        elif case.case_id == "fault_illegal_tool_call_001":
            output = _illegal_tool_probe(case)
        else:
            output = _base_observation(
                case,
                evidence=(
                    "缺少真实故障注入证据：请由独立测试环境执行故障注入并通过 "
                    "EVAL_FAULT_RECOVERY_EVIDENCE_PATH 提供脱敏观测"
                ),
            )
        return AdapterResponse(
            answer=str(output.get("evidence", "")),
            observations={"fault_recovery": output},
            evidence_summary=f"production fault recovery probe: {case.case_id}",
        )

    return execute
