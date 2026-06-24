"""navigate_to_page — 页面跳转状态变更工具

所属层：tools
依赖：src.schemas.action_agent
对接算法层：N/A（纯状态变更，下发 UIAction 跳转信号）

此工具不调用外部 API，仅将 LLM 决定的路由和参数
封装为 UIAction 对象，由 v3_engine_router 写入 AgentState.pending_actions。
前端 SSE 流消费 pending_actions 后执行 router.push()。
"""
import logging
from typing import Any, Dict

from src.schemas.action_agent import UIAction

logger = logging.getLogger(__name__)


def navigate_to_page(route: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
    """下发页面跳转信号，将 UIAction 写入 AgentState.pending_actions。

    Args:
        route: 目标路由（如 /analysis/consumption-panel, /coordination/energy）
        params: 路由参数（如 {"site_id": "SH-01", "chiller_id": "CH-01"}）

    Returns:
        UIAction 的 dict 表示
    """
    try:
        action = UIAction(
            type="navigate",
            route=route,
            params=params or {},
        )
        logger.info(f"navigate_to_page: route={route}, params={params}")
        return action.model_dump()
    except Exception as e:
        logger.error(f"navigate_to_page 失败: {e}")
        return {"error": f"navigate_to_page: {e}"}
