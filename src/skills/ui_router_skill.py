"""ui_router_skill — 监控页面查询与跳转技能

所属层：skills
依赖：src.tools.navigate_to_page, src.tools.java_backend, src.schemas.action_agent
对接算法层：N/A（Java 后端监控 API）

SOP：
  1. 识别查询意图 — 根据 LLM 调用的 Java 工具类型判断用户查询目标
  2. Java 工具取数 — 由 v3_engine_router 通过 TOOL_REGISTRY 执行
  3. 文字总结 — 由 LLM（interpreter_generator）生成流式 token 输出
  4. UIAction 生成 — 本 Skill 根据工具调用结果推断跳转路由

Skill 的职责集中在第 4 步：接收本轮工具调用结果，决定是否下发 UIAction。
优先使用 LLM 显式调用的 navigate_to_page，其次根据 Java 工具类型自动推断。

Java 工具（fetch_cop_data 等）在 Phase 4 替换为真实 HTTP，此 Skill 无需改动。

Prompt keys（src/config/prompts/ui_router.yaml）：
  - action_agent_nav_hint : 路由表 + 跳转时机判断指令
"""
import logging
from difflib import SequenceMatcher
from typing import Any, Dict, List, Tuple

from src.config.settings import settings
from src.schemas.action_agent import UIAction
from src.skills.base_skill import BaseSkill

logger = logging.getLogger(__name__)


class RouteRegistry:
    """路由注册表管理器，从 config/routes.yaml 加载路由映射。"""

    def __init__(self):
        """初始化路由注册表，从 settings.routes 加载。"""
        routes_config = settings.routes
        self.accessible = routes_config.get("accessible_routes", [])
        self.restricted = routes_config.get("restricted_routes", [])

    def find_route(self, keyword: str) -> Dict[str, Any]:
        """根据关键词模糊匹配路由。

        Args:
            keyword: 用户输入的页面描述（如"能源监控"、"工单列表"）

        Returns:
            匹配结果字典:
            {
                "path": "/integrated-monitor/energy-monitor",
                "name": "能源监控",
                "is_restricted": False,
                "restriction_reason": None
            }
            或 {"error": "未找到匹配的页面: xxx"}
        """
        best_match = None
        best_score = 0.0

        # 先匹配可访问路由
        for route in self.accessible:
            for kw in route.get("keywords", []):
                score = SequenceMatcher(None, keyword, kw).ratio()
                if score > best_score:
                    best_score = score
                    best_match = {
                        "path": route["path"],
                        "name": route["name"],
                        "is_restricted": False,
                        "restriction_reason": None,
                    }

        # 再匹配受限路由
        for route in self.restricted:
            for kw in route.get("keywords", []):
                score = SequenceMatcher(None, keyword, kw).ratio()
                if score > best_score:
                    best_score = score
                    best_match = {
                        "path": route["path"],
                        "name": route["name"],
                        "is_restricted": True,
                        "restriction_reason": route["reason"],
                    }

        if best_score < 0.6:  # 相似度阈值
            return {"error": f"未找到匹配的页面: {keyword}"}

        return best_match


# 全局单例
_route_registry = RouteRegistry()


def _build_tool_route_map() -> Dict[str, List[str]]:
    """从 routes.yaml 动态构建工具→路由映射。

    遍历所有路由配置，收集每个工具对应的页面路由。
    一个工具可以映射到多个路由（如 fetch_energy_summary 对应能耗分析和光储）。

    Returns:
        {tool_name: [route_path, ...], ...}
    """
    tool_map: Dict[str, List[str]] = {}
    routes_config = settings.routes
    all_routes = routes_config.get("accessible_routes", []) + routes_config.get("restricted_routes", [])
    for route in all_routes:
        for tool in route.get("tools", []):
            path = route["path"]
            if tool not in tool_map:
                tool_map[tool] = []
            if path not in tool_map[tool]:
                tool_map[tool].append(path)
    return tool_map


def _build_route_name_map() -> Dict[str, str]:
    """从 routes.yaml 构建路由路径→页面名称映射。

    Returns:
        {"/analysis/consumption-panel": "能耗分析", ...}
    """
    name_map: Dict[str, str] = {}
    routes_config = settings.routes
    all_routes = routes_config.get("accessible_routes", []) + routes_config.get("restricted_routes", [])
    for route in all_routes:
        name_map[route["path"]] = route.get("name", "")
    return name_map


def _normalize_route(route: str) -> str:
    """标准化路由路径，确保以 / 开头。

    Args:
        route: 原始路由路径

    Returns:
        标准化后的路由（如 "smart-maintenance/xxx" → "/smart-maintenance/xxx"）
    """
    return route if route.startswith("/") else f"/{route}"


# 启动时从 routes.yaml 构建一次
_TOOL_ROUTE_MAP: Dict[str, List[str]] = _build_tool_route_map()
_ROUTE_NAME_MAP: Dict[str, str] = _build_route_name_map()


class UIRouterSkill(BaseSkill):
    """监控页面查询与跳转技能。

    v3_engine_router 执行完本轮工具调用后，将结果列表传给 infer_navigation()，
    由 Skill 根据 SOP 决定是否生成 UIAction。router 节点不含业务逻辑。
    """

    name = "ui_router"
    tools = [
        "navigate_to_page",
        "fetch_cop_data",
        "fetch_energy_summary",
        "fetch_active_alarms",
        "fetch_carbon_info",
        "fetch_photovoltaic_monthly",
        "fetch_photovoltaic_daily",
        "fetch_pv_forecast",
        "fetch_load_forecast",
        "fetch_pv_forecast_range",
        "fetch_load_forecast_range",
        "fetch_electricity_forecast",
        "fetch_electricity_forecast_range",
        "fetch_energy_usage",
        "fetch_device_rank",
        "fetch_environment_params",
        "fetch_efficiency_calendar",
        "fetch_efficiency_detail",
        "fetch_energy_range",
        "fetch_alarm_history",
        "export_data_table",
    ]
    prompt_keys = ["action_agent_nav_hint", "data_visualization_hint"]
    description = "监控查询、页面跳转与数据卡片下发（ChartSpec JSON + 表格 + CSV）"

    def execute(
        self,
        tool_results: List[Tuple[str, Dict[str, Any], Dict[str, Any]]],
        state: Dict[str, Any],
    ) -> Dict[str, Any]:
        """根据工具调用结果推断页面跳转 + 数据卡片，返回 AgentState 更新。

        优先级：
          1. LLM 显式调用了 navigate_to_page → 原样采用
          2. LLM 调用了 Java 后端工具 → 根据工具类型自动映射路由
          3. LLM 调用了 export_data_table → 提取 DataCard 下发

        Args:
            tool_results: [(tool_name, result_dict, args_dict), ...]
            state: 当前 AgentState（只读）

        Returns:
            AgentState 更新字典（pending_actions / pending_data_cards），无匹配时返回空
        """
        updates: Dict[str, Any] = {}

        actions = self._infer_navigation(tool_results)
        if actions:
            logger.info(f"[DEBUG] UIRouterSkill 生成 {len(actions)} 个跳转: {actions}")
            updates["pending_actions"] = actions
        else:
            logger.info(f"[DEBUG] UIRouterSkill 未生成跳转")

        cards = self._infer_data_cards(tool_results)
        if cards:
            logger.info(f"[DEBUG] UIRouterSkill 生成 {len(cards)} 个数据卡片")
            updates["pending_data_cards"] = cards

        return updates

    @staticmethod
    def _infer_navigation(
        tool_results: List[Tuple[str, Dict[str, Any], Dict[str, Any]]],
    ) -> List[UIAction]:
        """SOP 核心：根据本轮工具调用结果推断页面跳转。

        优先级：
          1. LLM 显式调用了 navigate_to_page → 原样采用
          2. LLM 调用了 Java 后端工具 → 根据工具类型自动映射路由

        支持多意图场景，可返回多个 UIAction（按工具调用顺序排列）。
        相同路由只保留第一个，避免重复跳转。
        所有路由标准化为 / 开头，并自动填充页面名称。

        Args:
            tool_results: [(tool_name, result_dict, args_dict), ...]

        Returns:
            UIAction 列表，无匹配时返回空列表
        """
        seen_routes = set()
        actions: List[UIAction] = []

        # 优先：LLM 显式调用了 navigate_to_page
        for name, result, args in tool_results:
            if name == "navigate_to_page" and "error" not in result:
                try:
                    # 标准化路由格式（确保以 / 开头）
                    raw_route = result.get("route", "")
                    normalized_route = _normalize_route(raw_route)
                    result_copy = {**result, "route": normalized_route}
                    # 自动填充页面名称
                    if not result_copy.get("name"):
                        result_copy["name"] = _ROUTE_NAME_MAP.get(normalized_route, "")
                    action = UIAction(**result_copy)
                    if normalized_route not in seen_routes:
                        seen_routes.add(normalized_route)
                        actions.append(action)
                        logger.info(
                            f"UIRouterSkill: 采用 LLM 显式跳转 → {action.route} ({action.name})"
                        )
                except Exception as e:
                    logger.warning(f"UIRouterSkill: navigate_to_page 结果解析失败: {e}")

        # 兜底：Java 后端工具 → 自动推断跳转路由（跳过已存在路由）
        for name, result, args in tool_results:
            routes = _TOOL_ROUTE_MAP.get(name)
            if routes and "error" not in result:
                for route in routes:
                    normalized_route = _normalize_route(route)
                    if normalized_route not in seen_routes:
                        seen_routes.add(normalized_route)
                        params = {k: v for k, v in args.items() if v is not None}
                        route_name = _ROUTE_NAME_MAP.get(normalized_route, "")
                        action = UIAction(
                            type="navigate",
                            route=normalized_route,
                            name=route_name,
                            params=params,
                        )
                        actions.append(action)
                        logger.info(
                            f"UIRouterSkill: 根据 {name} 自动推断跳转 → {normalized_route} ({route_name})"
                        )

        return actions

    @staticmethod
    def _infer_data_cards(
        tool_results: List[Tuple[str, Dict[str, Any], Dict[str, Any]]],
    ) -> List[Dict[str, Any]]:
        """从 export_data_table 工具结果中提取 DataCard 下发。

        export_data_table 工具已返回 DataCard dict（含 chart + table + download），
        本方法仅做透传：收集本轮所有 export_data_table 的成功结果，作为
        pending_data_cards 下发，由 SSE event: data_card 推送前端渲染图表、
        表格与下载按钮。

        Args:
            tool_results: [(tool_name, result_dict, args_dict), ...]

        Returns:
            DataCard dict 列表，无则空列表
        """
        cards: List[Dict[str, Any]] = []
        for name, result, _ in tool_results:
            if name != "export_data_table":
                continue
            if not isinstance(result, dict) or "error" in result:
                continue
            # 确认是 DataCard 结构（含 download.task_id），避免误传其他 dict
            download = result.get("download")
            if isinstance(download, dict) and download.get("task_id"):
                cards.append(result)
        return cards
