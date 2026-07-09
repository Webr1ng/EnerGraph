"""ui_contract_scorer — SSE、UIAction 与 DataCard 契约评分

所属层：tests
依赖：src.config.settings, benchmarks.scorers.base
对接算法层：N/A
"""
import re
from typing import Any, Dict, List

from benchmarks.adapters.base import AdapterResponse
from benchmarks.scorers.base import BaseScorer, ScoreBundle
from benchmarks.shared.result_models import EvalCase, GateResult, MetricResult
from src.config.settings import settings
from src.schemas.action_agent import UIAction
from src.schemas.data_card import DataCard


_EVENT_FIELDS: Dict[str, tuple[str, ...]] = {
    "thinking": ("text",),
    "tool_call": ("name", "args"),
    "tool_result": ("name", "result"),
    "rag_sources": (),
    "text": ("text",),
    "action": ("type", "route", "name", "params", "meta"),
    "data_card": ("card_type", "title", "table", "download"),
    "error": ("error",),
    "done": (),
}


def _schema_errors(events: List[Dict[str, Any]]) -> List[str]:
    """返回事件类型、必填字段和基础类型错误。"""
    errors: List[str] = []
    for index, item in enumerate(events):
        event_type = item.get("event")
        data = item.get("data")
        if event_type not in _EVENT_FIELDS or not isinstance(data, dict):
            errors.append(f"event[{index}] type/data invalid")
            continue
        missing = [field for field in _EVENT_FIELDS[event_type] if field not in data]
        if missing:
            errors.append(f"event[{index}] missing={missing}")
            continue
        try:
            if event_type == "action":
                UIAction.model_validate(data)
            elif event_type == "data_card":
                DataCard.model_validate(data)
        except Exception as exc:
            errors.append(f"event[{index}] schema={type(exc).__name__}")
    return errors


def _order_valid(events: List[Dict[str, Any]]) -> bool:
    """验证 Tool 因果顺序、终态位置以及 error 后不再输出业务事件。"""
    names = [item.get("event") for item in events]
    if not names or names[-1] != "done":
        return False
    tool_call_seen = False
    error_seen = False
    for name in names:
        if error_seen and name != "done":
            return False
        if name == "tool_call":
            tool_call_seen = True
        if name == "tool_result" and not tool_call_seen:
            return False
        if name == "error":
            error_seen = True
    return True


def _route_maps() -> tuple[Dict[str, str], set[str]]:
    """从真实路由配置构建可访问名称表和受限路由集合。"""
    accessible = {
        item["path"]: item.get("name", "")
        for item in settings.routes.get("accessible_routes", [])
    }
    restricted = {
        item["path"] for item in settings.routes.get("restricted_routes", [])
    }
    return accessible, restricted


class UIContractScorer(BaseScorer):
    """计算协议、终态、路由、DataCard 与正文去重指标。"""

    name = "ui_contract"

    def score(self, case: EvalCase, response: AdapterResponse) -> ScoreBundle:
        """生成六项满分制指标和对应硬门禁。"""
        events = response.protocol_events
        errors = _schema_errors(events)
        schema_valid = not errors
        order_valid = _order_valid(events)
        done_count = sum(item.get("event") == "done" for item in events)
        terminal_unique = done_count == 1 and bool(events) and events[-1].get("event") == "done"

        accessible, restricted = _route_maps()
        actions = [item.get("data", {}) for item in events if item.get("event") == "action"]
        routes = [action.get("route") for action in actions]
        invalid_actions = [
            action for action in actions
            if action.get("route") not in accessible
            or action.get("route") in restricted
            or action.get("name") != accessible.get(action.get("route"))
        ]
        action_valid = not invalid_actions and len(routes) == len(set(routes))

        cards = [item.get("data", {}) for item in events if item.get("event") == "data_card"]
        observation = response.observations.get("ui_contract", {})
        expected_rows = observation.get("source_rows")
        card_rows = [card.get("table", {}).get("rows") for card in cards]
        rows_match = all(rows == expected_rows for rows in card_rows) if cards else expected_rows is None
        rows_match = rows_match and observation.get("chart_rows", expected_rows) == expected_rows
        rows_match = rows_match and observation.get("csv_rows", expected_rows) == expected_rows
        cards_valid = all(
            isinstance(card.get("table", {}).get("columns"), list)
            and isinstance(card.get("table", {}).get("rows"), list)
            and bool(card.get("download", {}).get("task_id"))
            and str(card.get("download", {}).get("url", "")).startswith("/export/")
            for card in cards
        )
        data_card_valid = cards_valid and rows_match

        text_chunks = [
            item.get("data", {}).get("text", "")
            for item in events if item.get("event") == "text"
        ]
        final_text = "".join(text_chunks)
        duplicated = any(chunk and final_text.count(chunk) > 1 for chunk in text_chunks)
        forged_link = bool(re.search(r"https?://|\[[^]]+\]\(/export/", final_text))
        text_valid = not duplicated and not forged_link

        return ScoreBundle(
            metrics=[
                MetricResult(name="sse_schema_validity", score=float(schema_valid)),
                MetricResult(name="sse_order_accuracy", score=float(order_valid)),
                MetricResult(name="terminal_uniqueness", score=float(terminal_unique)),
                MetricResult(name="ui_action_validity", score=float(action_valid)),
                MetricResult(name="data_card_consistency", score=float(data_card_valid)),
                MetricResult(name="final_text_uniqueness", score=float(text_valid)),
            ],
            gates=[
                GateResult(name="invalid_sse_schema", violated=not schema_valid, evidence_summary=str(errors)),
                GateResult(name="invalid_sse_order", violated=not order_valid),
                GateResult(name="invalid_terminal_event", violated=not terminal_unique),
                GateResult(name="invalid_ui_action", violated=not action_valid),
                GateResult(name="datacard_rows_mismatch", violated=not data_card_valid),
                GateResult(name="forged_body_link_or_duplicate_text", violated=not text_valid),
            ],
        )
