"""工具注册表 — HVAC 知识库 + 福加运营数据 API Tools

所属层：tools
依赖：src.tools.*
对接算法层：HVAC RAG（ChromaDB 本地）/ 福加监控 API（REST）
"""
from typing import Any, Callable, Dict

from src.config.settings import settings
from src.tools.parse_intent import parse_business_intent
from src.tools.query_hvac_knowledge import query_hvac_knowledge
from src.tools.java_backend import (
    fetch_cop_data,
    fetch_energy_summary,
    fetch_active_alarms,
    fetch_carbon_info,
    fetch_photovoltaic_monthly,
    fetch_photovoltaic_daily,
    fetch_energy_usage,
    fetch_device_rank,
    fetch_environment_params,
    fetch_efficiency_calendar,
    fetch_efficiency_detail,
)
from src.tools.navigate_to_page import navigate_to_page


def _build_route_description() -> str:
    """从 routes.yaml 构建导航工具的路由说明。"""
    accessible = settings.routes.get("accessible_routes", [])
    restricted = settings.routes.get("restricted_routes", [])

    route_items = [
        f"{route['path']}（{route['name']}）"
        for route in accessible + restricted
        if route.get("path") and route.get("name")
    ]
    if not route_items:
        return "目标路由，必须以 / 开头"

    return "目标路由，必须以 / 开头。可用路由：" + "；".join(route_items)

TOOL_REGISTRY: Dict[str, Callable[..., Dict[str, Any]]] = {
    "parse_business_intent": parse_business_intent,
    "query_hvac_knowledge": query_hvac_knowledge,
    "fetch_cop_data": fetch_cop_data,
    "fetch_energy_summary": fetch_energy_summary,
    "fetch_active_alarms": fetch_active_alarms,
    "fetch_carbon_info": fetch_carbon_info,
    "fetch_photovoltaic_monthly": fetch_photovoltaic_monthly,
    "fetch_photovoltaic_daily": fetch_photovoltaic_daily,
    "fetch_energy_usage": fetch_energy_usage,
    "fetch_device_rank": fetch_device_rank,
    "fetch_environment_params": fetch_environment_params,
    "fetch_efficiency_calendar": fetch_efficiency_calendar,
    "fetch_efficiency_detail": fetch_efficiency_detail,
    "navigate_to_page": navigate_to_page,
}

TOOL_SCHEMAS = [
    {
        "name": "query_hvac_knowledge",
        "description": "从暖通空调（HVAC）专业知识库检索相关问答，用于回答暖通规范、能效计算、故障诊断、节能优化等专业问题",
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "用户的暖通空调相关问题"},
            },
            "required": ["question"],
        },
    },
    {
        "name": "fetch_cop_data",
        "description": "获取冷水机房的 COP（能效比）数据：机房累计COP（水系统平均SCOP，含冷水机+水泵+冷却塔整体）和机房瞬时COP（水系统瞬时SCOP），另含机组蒸发器/冷凝器温度与实时功率。回答机房COP、能效、冷水机组性能时使用",
        "parameters": {
            "type": "object",
            "properties": {
                "site_id": {"type": "string", "description": "站点 ID，如 FJJB000001"},
                "chiller_id": {"type": "string", "description": "冷水机组编号，默认 CH-01"},
            },
            "required": ["site_id"],
        },
    },
    {
        "name": "fetch_energy_summary",
        "description": "获取站点单日能耗汇总（优先使用此工具回答能耗问题）：总用电量、光伏发电、电网取电、储能充放电、峰值/平均负荷、碳减排。包含完整光储充分项。用户问'能耗''用电量+光伏''全厂能源'等都应调用此工具",
        "parameters": {
            "type": "object",
            "properties": {
                "site_id": {"type": "string", "description": "站点 ID，如 FJJB000001"},
                "date": {"type": "string", "description": "统计日期，格式 YYYY-MM-DD，默认今天"},
            },
            "required": ["site_id"],
        },
    },
    {
        "name": "fetch_active_alarms",
        "description": "获取站点当前活跃报警列表，包括报警级别、设备、报警信息和时间",
        "parameters": {
            "type": "object",
            "properties": {
                "site_id": {"type": "string", "description": "站点 ID，如 FJJB000001"},
            },
            "required": ["site_id"],
        },
    },
    {
        "name": "fetch_carbon_info",
        "description": "获取碳排信息：本月光伏发电量(kWh)、碳减排量(kgCO₂e)、累计碳减排、环比数据。回答光伏、碳减排、绿电等问题时使用",
        "parameters": {
            "type": "object",
            "properties": {
                "site_id": {"type": "string", "description": "站点 ID，如 FJJB000001"},
            },
            "required": ["site_id"],
        },
    },
    {
        "name": "fetch_photovoltaic_monthly",
        "description": "获取光伏月度发电量和收益明细，返回按月列表（每月发电量kWh + 收益元）。回答光伏收益、月度发电量趋势时使用",
        "parameters": {
            "type": "object",
            "properties": {
                "site_id": {"type": "string", "description": "站点 ID，如 FJJB000001"},
            },
            "required": ["site_id"],
        },
    },
    {
        "name": "fetch_photovoltaic_daily",
        "description": "获取指定日期的光伏发电量(kWh)和峰值功率(kW)。通过累加15分钟间隔功率数据计算日发电量。回答今天/某天发了多少光伏电时使用",
        "parameters": {
            "type": "object",
            "properties": {
                "site_id": {"type": "string", "description": "站点 ID，如 FJJB000001"},
                "date": {"type": "string", "description": "查询日期，格式 YYYY-MM-DD，默认今天"},
            },
            "required": ["site_id"],
        },
    },
    {
        "name": "fetch_energy_usage",
        "description": "获取全厂用电量（仅总用电量，不含光伏/储能分项）：今日用电量(kWh)、本月用电量(kWh)、环比百分比。仅回答纯用电量问题时使用。需要光伏/储能/电网分项数据请用 fetch_energy_summary",
        "parameters": {
            "type": "object",
            "properties": {
                "site_id": {"type": "string", "description": "站点 ID，如 FJJB000001"},
            },
            "required": ["site_id"],
        },
    },
    {
        "name": "fetch_device_rank",
        "description": "获取设备用电排名。rank_type=factory 返回全厂 Top5 设备排名(MWh)，rank_type=room 返回机房设备能耗占比和 COP",
        "parameters": {
            "type": "object",
            "properties": {
                "site_id": {"type": "string", "description": "站点 ID，如 FJJB000001"},
                "rank_type": {"type": "string", "description": "排名类型: factory(全厂设备排名) 或 room(机房设备排名)", "default": "factory"},
            },
            "required": ["site_id"],
        },
    },
    {
        "name": "fetch_environment_params",
        "description": "获取室外环境参数：温度(°C)、湿度(%)、湿球温度(°C)、焓值(kJ/kg)。回答天气、环境、温湿度等问题时使用",
        "parameters": {
            "type": "object",
            "properties": {
                "site_id": {"type": "string", "description": "站点 ID，如 FJJB000001"},
            },
            "required": ["site_id"],
        },
    },
    {
        "name": "fetch_efficiency_calendar",
        "description": "【制冷量查询首选】获取能效日历数据。mode=day 返回当月每天的 COP/制冷量/用电量，mode=month 返回月度汇总（机房当月用电量 electricity、COP、制冷量、电费、电价）。回答今日制冷量、某天制冷量、每日COP、能效日历、月度能效评价、机房某月能耗/月用电量时使用。查单日制冷量必须用 mode=day（包括今天），不要用 fetch_efficiency_detail 的累计制冷量",
        "parameters": {
            "type": "object",
            "properties": {
                "site_id": {"type": "string", "description": "站点 ID，如 FJJB000001"},
                "date": {"type": "string", "description": "查询日期，格式 YYYY-MM（如 2026-06），默认当月"},
                "mode": {"type": "string", "description": "模式: day(日度数据) 或 month(月度汇总，用于查机房月用电量)", "default": "day"},
            },
            "required": ["site_id"],
        },
    },
    {
        "name": "fetch_efficiency_detail",
        "description": "通用能效查询：按参数名查询机房任意能效指标的当前值。可用参数: 水系统平均COP, 冷水主机平均COP, 水系统平均SCOP, 水系统瞬时SCOP, 水系统瞬时制冷量, 水系统累计制冷量（⚠️ 此为开机以来累计值，非单日制冷量！查今日/某天制冷量请用 fetch_efficiency_calendar mode=day）, 水系统瞬时功率, 水系统累计电能, 水系统热平衡系数。用户问到具体设备级参数（如某台冷水机组的COP、某个水泵的功率）时，回答'该参数暂不支持自动查询'并跳转到 /analysis/query 让用户自行查看",
        "parameters": {
            "type": "object",
            "properties": {
                "site_id": {"type": "string", "description": "站点 ID，如 FJJB000001"},
                "param_name": {"type": "string", "description": "查询参数名，可选值: 水系统平均COP, 冷水主机平均COP, 水系统平均SCOP, 水系统瞬时SCOP, 水系统瞬时制冷量, 水系统累计制冷量, 水系统瞬时功率, 水系统累计电能, 水系统热平衡系数"},
            },
            "required": ["site_id", "param_name"],
        },
    },
    {
        "name": "navigate_to_page",
        "description": "下发页面跳转信号，将用户导航到指定监控页面。在获取监控数据后，根据数据类型跳转到对应的详情页面",
        "parameters": {
            "type": "object",
            "properties": {
                "route": {
                    "type": "string",
                    "description": _build_route_description(),
                },
                "params": {
                    "type": "object",
                    "description": "路由参数，如 {\"site_id\": \"SH-01\", \"chiller_id\": \"CH-01\"}",
                },
            },
            "required": ["route"],
        },
    },
]
