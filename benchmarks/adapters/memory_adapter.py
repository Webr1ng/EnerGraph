"""memory_adapter — 长期记忆 Store 的 Eval Adapter 边界

所属层：tests
依赖：benchmarks.adapters.base, src.memory.store, src.graph.nodes
对接算法层：N/A
"""
from typing import Any, Callable, Dict

from benchmarks.adapters.base import AdapterResponse, BaseAdapter
from benchmarks.shared.config_models import EvalRunConfig
from benchmarks.shared.result_models import EvalCase


class MemoryAdapter(BaseAdapter):
    """适配 InMemory 或 PostgreSQL 记忆执行器。"""

    adapter_name = "memory"


def _scope_for_type(memory_type: str) -> str:
    """将记忆类型映射为 Store scope。"""
    return {
        "user_preference": "user_preference",
        "site_fact": "site",
        "safety_constraint": "safety_constraint",
        "decision_history": "decision_history",
        "device_state": "device_state",
    }.get(memory_type, "session_note")


def create_memory_benchmark_executor() -> Callable:
    """创建执行 Memory v0.1 Fixture 场景的 InMemory 执行器。"""
    from src.config.settings import settings
    from src.graph.nodes import _candidate_passes_quality_gate
    from src.memory.store import get_memory_store
    from src.schemas.memory import MemoryCandidate, MemoryQuery
    from src.tools.memory_ops import save_memory

    def execute(case: EvalCase, _config: EvalRunConfig, _namespace: str) -> AdapterResponse:
        """执行候选写入、检索、隔离、TTL 或 upsert 场景。"""
        scenario: Dict[str, Any] = case.fixtures.get("memory_scenario", {})
        context = case.fixtures.get("memory_context", {})
        original_env = settings.memory.env
        settings.memory.env = context.get("env", original_env)
        site_id = context.get("site_id", case.input.site_id)
        agent_id = context.get("agent_id", "main_graph")
        user_id = context.get("user_id", case.input.user_id)
        thread_id = context.get("thread_id", case.input.thread_id)
        aliases_by_content: Dict[str, str] = {}
        writes: list[dict] = []

        def write_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
            memory_type = entry.get("memory_type", "session_note")
            alias = entry.get("alias", entry.get("memory_key", entry["content"]))
            aliases_by_content[entry["content"]] = alias
            metadata = {
                "memory_type": memory_type,
                "source_thread_id": thread_id,
                "site_id": site_id,
                "agent_id": agent_id,
                "confidence": entry.get("confidence", 0.95),
                "ttl_seconds": entry.get("ttl_seconds"),
                "valid_until": entry.get("valid_until"),
            }
            return save_memory(
                content=entry["content"], agent_id=agent_id, site_id=site_id,
                scope=_scope_for_type(memory_type),
                entity_id=(
                    user_id if memory_type == "user_preference"
                    else site_id if memory_type in {"site_fact", "safety_constraint", "device_state"}
                    else thread_id
                ),
                metadata=metadata,
                memory_key=entry.get("memory_key", ""), user_id=user_id,
            )

        try:
            action = scenario.get("action")
            if action == "candidate":
                candidate = MemoryCandidate(**scenario["candidate"])
                if _candidate_passes_quality_gate(candidate):
                    result = write_entry(candidate.model_dump(mode="json", exclude_none=True))
                    if result.get("memory"):
                        writes.append({
                            "memory_type": candidate.memory_type,
                            "memory_key": candidate.memory_key,
                            "content": candidate.content,
                            "ttl_seconds": candidate.ttl_seconds,
                            "valid_until": result["memory"]["metadata"].get("valid_until"),
                        })
            elif action in {"search", "isolation", "expired"}:
                for entry in scenario.get("setup", []):
                    write_entry(entry)
            elif action == "upsert":
                key = scenario["memory_key"]
                first = {
                    "content": scenario["first_content"], "memory_type": "user_preference",
                    "memory_key": key,
                }
                latest = {
                    "content": scenario["latest_content"], "memory_type": "user_preference",
                    "memory_key": key,
                }
                write_entry(first)
                result = write_entry(latest)
                writes.append({
                    "memory_type": "user_preference", "memory_key": key,
                    "content": scenario["latest_content"],
                })

            query_site = site_id
            query_agent = agent_id
            query_scope = "user_preference"
            query_entity = user_id
            if action == "isolation":
                if scenario.get("dimension") == "site":
                    query_site = f"{site_id}_other"
                else:
                    query_agent = f"{agent_id}_other"
                setup_type = scenario.get("setup", [{}])[0].get("memory_type", "session_note")
                query_scope = _scope_for_type(setup_type)
                query_entity = site_id if setup_type in {"site_fact", "safety_constraint"} else thread_id
            elif action == "expired":
                query_scope = "device_state"
                query_entity = site_id

            retrieved_aliases: list[str] = []
            latest_content = None
            if action in {"search", "isolation", "expired", "upsert"}:
                result = get_memory_store().search(MemoryQuery(
                    query=scenario.get("query", ""), agent_id=query_agent, site_id=query_site,
                    scope=query_scope, entity_id=query_entity, limit=5,
                ))
                retrieved_aliases = [
                    aliases_by_content.get(item.content, item.content) for item in result.memories
                ]
                latest_content = result.memories[0].content if result.memories else None

            observation = {
                "writes": writes,
                "retrieved_aliases": retrieved_aliases,
                "latest_content": latest_content,
                "leaked_aliases": retrieved_aliases if action == "isolation" else [],
                "stale_used_aliases": retrieved_aliases if action == "expired" else [],
                "deleted_used_aliases": [],
                "safety_constraint_violated": False,
            }
            return AdapterResponse(
                observations={"memory": observation},
                evidence_summary=f"memory action={action}; env={settings.memory.env}",
            )
        finally:
            settings.memory.env = original_env

    return execute


def memory_namespace_cleaner(_namespace: str) -> None:
    """清空 Memory Fast Store，保证案例之间无状态污染。"""
    from src.memory.store import get_memory_store, reset_memory_store

    get_memory_store().clear()
    reset_memory_store()
