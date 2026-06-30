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
    fetch_monthly_alarm_count,
    fetch_carbon_info,
    fetch_photovoltaic_monthly,
    fetch_photovoltaic_daily,
    fetch_pv_forecast,
    fetch_load_forecast,
    fetch_energy_usage,
    fetch_device_rank,
    fetch_environment_params,
    fetch_efficiency_calendar,
    fetch_efficiency_detail,
    fetch_energy_range,
    fetch_alarm_history,
)
from src.tools.export_data import export_data_table
from src.tools.memory_ops import save_memory, search_memory, search_relevant_memory
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
    "fetch_monthly_alarm_count": fetch_monthly_alarm_count,
    "fetch_carbon_info": fetch_carbon_info,
    "fetch_photovoltaic_monthly": fetch_photovoltaic_monthly,
    "fetch_photovoltaic_daily": fetch_photovoltaic_daily,
    "fetch_pv_forecast": fetch_pv_forecast,
    "fetch_load_forecast": fetch_load_forecast,
    "fetch_energy_usage": fetch_energy_usage,
    "fetch_device_rank": fetch_device_rank,
    "fetch_environment_params": fetch_environment_params,
    "fetch_efficiency_calendar": fetch_efficiency_calendar,
    "fetch_efficiency_detail": fetch_efficiency_detail,
    "fetch_energy_range": fetch_energy_range,
    "fetch_alarm_history": fetch_alarm_history,
    "export_data_table": export_data_table,
    "navigate_to_page": navigate_to_page,
    "search_memory": search_memory,
    "search_relevant_memory": search_relevant_memory,
    "save_memory": save_memory,
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
        "description": "获取站点当前活跃报警列表，包括报警级别、设备、报警信息和时间。仅查询最近 N 天的活跃报警，不包含历史报警。回答「本月报警数」「本月报警统计」等月度报警问题时，请使用 fetch_monthly_alarm_count（会同时查询实时+历史报警并累加总数）",
        "parameters": {
            "type": "object",
            "properties": {
                "site_id": {"type": "string", "description": "站点 ID，如 FJJB000001"},
            },
            "required": ["site_id"],
        },
    },
    {
        "name": "fetch_monthly_alarm_count",
        "description": "【月度报警统计首选】获取指定月份的报警总数（实时报警 + 历史报警累加）。同时查询 listRealAlarms 和 listHisAlarms 两个接口，返回两者 total 的累加和。回答「本月报警数」「这个月有多少报警」「月度报警统计」等月度报警总览问题时使用此工具",
        "parameters": {
            "type": "object",
            "properties": {
                "site_id": {"type": "string", "description": "站点 ID，如 FJJB000001"},
                "date": {"type": "string", "description": "查询月份，格式 YYYY-MM，默认当月"},
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
        "name": "fetch_pv_forecast",
        "description": "【光伏预测查询首选】获取光伏预测 vs 实际对比 + 准确率 + 天气预报（福加 loadForecast 接口，对应 /analysis/pv-forecast 页面）。一次返回四块：所选日期/周的预测vs实际曲线、天气预报（日=逐时温湿度，周=每日最高/最低/湿度）、昨日对比、上周对比；今日查询额外带准确率/评估等级/下一小时预测。回答「光伏预测」「预测准不准/准确率」「今日/昨日/上周光伏预测」「光伏天气预报」「这周每天光伏预测」时使用。注意：问实际发电量/收益用 fetch_photovoltaic_daily，问预测对比/准确率/天气用本工具",
        "parameters": {
            "type": "object",
            "properties": {
                "site_id": {"type": "string", "description": "站点 ID，如 FJJB000001"},
                "date": {"type": "string", "description": "参考日期 YYYY-MM-DD，默认今天；unit=week 时传该周内任意一天，工具自动取周一~周日"},
                "unit": {"type": "string", "description": "查询粒度: day(按日，默认) 或 week(按周，查「这周/某周」时用)", "default": "day"},
            },
            "required": ["site_id"],
        },
    },
    {
        "name": "fetch_load_forecast",
        "description": "【冷负荷预测查询首选】获取冷负荷预测 vs 实际对比 + 平均偏差 + 天气预报（福加 loadForecast 接口，energyType=load，对应 /analysis/load-forecast 页面）。一次返回四块：所选日期/周的预测vs实际曲线、天气预报（日=逐时温湿度，周=每日最高/最低/湿度）、昨日对比、上周对比；今日查询额外带左上小面板——今日平均偏差(accuracy)、当前负荷(current_load_kw)、预测负荷(predicted_load_kw)、下小时预测(next_hour_forecast_kw)及评估等级。回答「负荷预测」「冷负荷预测」「预测负荷」「当前负荷/预测负荷」「负荷预测准不准/平均偏差」「今日/昨日/上周负荷预测」时使用。注意：问光伏预测用 fetch_pv_forecast，问冷负荷预测用本工具",
        "parameters": {
            "type": "object",
            "properties": {
                "site_id": {"type": "string", "description": "站点 ID，如 FJJB000001"},
                "date": {"type": "string", "description": "参考日期 YYYY-MM-DD，默认今天；unit=week 时传该周内任意一天，工具自动取周一~周日"},
                "unit": {"type": "string", "description": "查询粒度: day(按日，默认) 或 week(按周，查「这周/某周」时用)", "default": "day"},
            },
            "required": ["site_id"],
        },
    },
    {
        "name": "fetch_energy_usage",
        "description": "【全厂用电量查询首选】获取全厂今日用电量(kWh)和本月用电量(kWh)。回答「全厂今日用电量」「全厂本月用电量」「今天用了多少电」「这个月用了多少电」等纯用电量总额问题时使用。数据来源与首页一致。需要光伏/储能/电网分项数据请用 fetch_energy_summary。查询后跳转到 /index/index（首页）",
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
    {
        "name": "search_memory",
        "description": "按显式 scope/entity/namespace 检索当前 Agent 的长期记忆。需要精确读取某个记忆域时使用；询问'记得什么/长期信息/运行约束/站点事实/设备状态'等概括问题时优先用 search_relevant_memory",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索问题或关键词"},
                "agent_id": {"type": "string", "description": "Agent ID，如 main_graph/hvac_expert/powerai/ui_router", "default": "main_graph"},
                "site_id": {"type": "string", "description": "站点 ID，如 FJJB000001；无站点时填 local", "default": "local"},
                "scope": {"type": "string", "description": "记忆范围，如 user_preference/site_fact/session_note", "default": "session_note"},
                "entity_id": {"type": "string", "description": "记忆实体 ID，如 user_001/FJJB000001/default", "default": "default"},
                "namespace": {"type": "array", "items": {"type": "string"}, "description": "显式 namespace；仅在需要跨 Agent/跨 scope 读取时使用"},
                "memory_types": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["user_preference", "site_fact", "decision_history", "device_state", "safety_constraint", "session_note"],
                    },
                    "description": "记忆类型过滤",
                },
                "limit": {"type": "integer", "description": "返回条数，1-20", "default": 5},
            },
            "required": [],
        },
    },
    {
        "name": "search_relevant_memory",
        "description": "跨常用长期记忆域聚合检索：用户偏好、站点事实、运行安全约束、已确认决策、临时设备状态、旧 session_note。用户询问'你知道/你记得/长期信息/运行约束/站点事实/设备状态'时使用",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索问题或关键词"},
                "agent_id": {"type": "string", "description": "Agent ID，如 main_graph/hvac_expert/powerai/ui_router", "default": "main_graph"},
                "site_id": {"type": "string", "description": "站点 ID，如 FJJB000001；无站点时填 local", "default": "local"},
                "thread_id": {"type": "string", "description": "当前会话 thread_id，用于检索用户偏好、决策历史和旧 session_note", "default": "unknown"},
                "limit": {"type": "integer", "description": "最终返回条数，1-20，默认 10", "default": 10},
                "include_expired": {"type": "boolean", "description": "是否包含过期 device_state，默认 false", "default": False},
            },
            "required": [],
        },
    },
    {
        "name": "save_memory",
        "description": "显式写入当前 Agent 的长期记忆。只保存稳定偏好、站点事实、已确认决策或安全约束；临时设备状态/告警/单次策略必须带 ttl_seconds 或 valid_until",
        "parameters": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "简洁的记忆正文"},
                "agent_id": {"type": "string", "description": "Agent ID，如 main_graph/hvac_expert/powerai/ui_router", "default": "main_graph"},
                "site_id": {"type": "string", "description": "站点 ID，如 FJJB000001；无站点时填 local", "default": "local"},
                "scope": {"type": "string", "description": "记忆范围，如 user_preference/site_fact/session_note", "default": "session_note"},
                "entity_id": {"type": "string", "description": "记忆实体 ID，如 user_001/FJJB000001/default", "default": "default"},
                "namespace": {"type": "array", "items": {"type": "string"}, "description": "显式 namespace；仅在需要写入特定记忆域时使用"},
                "metadata": {
                    "type": "object",
                    "description": "记忆元数据，包含 memory_type/source_thread_id/site_id/agent_id/confidence/valid_until/ttl_seconds/tags",
                    "properties": {
                        "memory_type": {
                            "type": "string",
                            "enum": ["user_preference", "site_fact", "decision_history", "device_state", "safety_constraint", "session_note"],
                            "default": "session_note",
                        },
                        "source_thread_id": {"type": "string", "description": "来源 thread_id", "default": "unknown"},
                        "site_id": {"type": "string", "description": "站点 ID", "default": "local"},
                        "agent_id": {"type": "string", "description": "Agent ID", "default": "main_graph"},
                        "confidence": {"type": "number", "description": "置信度 0-1", "default": 0.8},
                        "valid_until": {"type": "string", "description": "ISO8601 有效期截止时间"},
                        "ttl_seconds": {"type": "integer", "description": "相对 TTL 秒数；临时状态必填"},
                        "tags": {"type": "array", "items": {"type": "string"}, "description": "标签"},
                    },
                },
            },
            "required": ["content"],
        },
    },
    {
        "name": "fetch_energy_range",
        "description": "【数据导出-多日能耗】获取站点多日能耗汇总（逐日复用 fetch_energy_summary）。用户问「最近N天/最近一周/某时段的能耗数据并导出/下载」时用此工具取多日数据，再调 export_data_table 生成 CSV。返回 items 为每日 EnergySummary 列表。日期 YYYY-MM-DD，「最近7天」= start_date 今天往前推6天、end_date 今天",
        "parameters": {
            "type": "object",
            "properties": {
                "site_id": {"type": "string", "description": "站点 ID，如 FJJB000001"},
                "start_date": {"type": "string", "description": "起始日期 YYYY-MM-DD，默认今天往前推6天"},
                "end_date": {"type": "string", "description": "结束日期 YYYY-MM-DD，默认今天"},
            },
            "required": ["site_id"],
        },
    },
    {
        "name": "fetch_alarm_history",
        "description": "【数据导出-历史报警】获取站点历史报警明细（按日期范围）。用户问「导出本月/最近N天报警记录」时用此工具取报警明细，再调 export_data_table 生成 CSV。返回 items 为 AlarmItem 列表（alarm_id/level/device/message/timestamp/acknowledged）",
        "parameters": {
            "type": "object",
            "properties": {
                "site_id": {"type": "string", "description": "站点 ID，如 FJJB000001"},
                "start_date": {"type": "string", "description": "起始日期 YYYY-MM-DD，默认今天往前推6天"},
                "end_date": {"type": "string", "description": "结束日期 YYYY-MM-DD，默认今天"},
            },
            "required": ["site_id"],
        },
    },
    {
        "name": "export_data_table",
        "description": "【数据导出-通用】将任意表格数据生成可下载 CSV 并下发数据卡片（前端显示表格+下载按钮）。用户表达「导出/下载表格」意图时，先用范围查询工具（fetch_energy_range/fetch_alarm_history）取数据，再调本工具。columns 用中文表头+单位，rows 为行数据（每行 {key:value}）。下载按钮自动出现，无需在回答中提供下载链接",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "卡片标题，如 FJJB000001 近7天能耗汇总"},
                "columns": {
                    "type": "array",
                    "description": "列定义，每项 {key, label, unit?}。key 为 rows 中字段名，label 为中文表头，unit 为单位（可省）",
                    "items": {
                        "type": "object",
                        "properties": {
                            "key": {"type": "string", "description": "行数据字段名（snake_case）"},
                            "label": {"type": "string", "description": "中文表头"},
                            "unit": {"type": "string", "description": "单位（可省）"},
                        },
                        "required": ["key", "label"],
                    },
                },
                "rows": {
                    "type": "array",
                    "description": "行数据列表，每行为 {字段名: 值}",
                    "items": {"type": "object"},
                },
                "filename": {"type": "string", "description": "下载文件名（可省，默认自动生成）"},
            },
            "required": ["title", "columns", "rows"],
        },
    },
]
