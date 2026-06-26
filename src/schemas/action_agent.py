"""action_agent — Action Agent 数据模型

所属层：schemas
依赖：pydantic
对接算法层：N/A
"""
from typing import Optional
from pydantic import BaseModel, Field


class PageContext(BaseModel):
    """前端页面上下文，由前端在每次请求时注入。

    字段会随前端页面分析逐步扩展。params 承载页面级运行时数据
    （如筛选条件、选中的设备 ID），新增字段直接追加，无需破坏现有结构。
    """
    current_route: str = Field(default="/", description="当前页面路由")
    site_id: Optional[str] = Field(default=None, description="当前选中的站点 ID")
    params: dict = Field(default_factory=dict, description="页面级运行时参数（筛选条件、选中设备等）")
    meta: dict = Field(default_factory=dict, description="扩展元数据，后续前端分析追加字段用此入口")


class ActionAgentInput(BaseModel):
    """POST /stream 请求体。"""
    user_input: str = Field(..., description="用户输入文本")
    page_context: Optional[PageContext] = Field(default=None, description="前端页面上下文")
    thread_id: Optional[str] = Field(default=None, description="会话线程 ID，用于 LangGraph checkpoint 隔离")


class UIAction(BaseModel):
    """前端可消费的 UI 动作信号。

    当前支持页面跳转；后续前端页面分析后，可扩展子页面跳转、
    面包屑导航、高亮组件、打开面板等动作。新增字段直接追加，
    params 承载路由参数，meta 承载 UI 层元数据。
    """
    type: str = Field(default="navigate", description="动作类型：navigate / highlight / open_panel（后续前端分析追加）")
    route: str = Field(..., description="目标路由，子页面用 /parent/child 形式，始终以 / 开头")
    name: str = Field(default="", description="页面名称（如'能耗分析'、'设备运行'），从 routes.yaml 自动填充")
    params: dict = Field(default_factory=dict, description="路由参数（如 site_id, chiller_id）")
    meta: dict = Field(default_factory=dict, description="UI 元数据（面包屑、查询参数、高亮目标等，后续前端分析追加）")


# ── Java 后端工具输出模型（Phase 2 T3）──────────────────────────────

class COPData(BaseModel):
    """冷水机房 COP（能效比）数据。

    机房COP = 整个冷水机房（冷水机组+冷水泵+冷却水泵+冷却塔）的综合能效。
    取值来源：queryPointEnergyEfficiency 的 SCOP 点位当日末值。
    """
    site_id: str = Field(..., description="站点 ID")
    chiller_id: str = Field(..., description="冷水机组编号")
    instant_cop: float = Field(..., description="机房瞬时COP（水系统瞬时SCOP）")
    cumulative_cop: float = Field(..., description="机房COP（水系统平均SCOP，即用户看到的机房平均COP）")
    chilled_water_out_temp: float = Field(..., description="冷冻水出水温度 (℃)")
    cooling_water_in_temp: float = Field(..., description="冷却水进水温度 (℃)")
    power_kw: float = Field(..., description="实时功率 (kW)")
    timestamp: str = Field(..., description="数据时间戳 (ISO 8601)")
    status: str = Field(default="normal", description="运行状态")


class EnergySummary(BaseModel):
    """站点能耗汇总数据。"""
    site_id: str = Field(..., description="站点 ID")
    date: str = Field(..., description="统计日期 (YYYY-MM-DD)")
    total_consumption_kwh: float = Field(..., description="总用电量 (kWh)")
    pv_generation_kwh: float = Field(default=0.0, description="光伏发电量 (kWh)")
    grid_import_kwh: float = Field(..., description="电网取电量 (kWh)")
    storage_charge_kwh: float = Field(default=0.0, description="储能充电量 (kWh)")
    storage_discharge_kwh: float = Field(default=0.0, description="储能放电量 (kWh)")
    peak_load_kw: float = Field(..., description="峰值负荷 (kW)")
    avg_load_kw: float = Field(..., description="平均负荷 (kW)")
    carbon_reduction_kg: float = Field(default=0.0, description="碳减排量 (kgCO₂)")


class AlarmItem(BaseModel):
    """单条报警记录。"""
    alarm_id: str = Field(..., description="报警 ID")
    level: str = Field(..., description="报警级别：critical / warning / info")
    device: str = Field(..., description="报警设备名称")
    message: str = Field(..., description="报警信息")
    timestamp: str = Field(..., description="报警时间 (ISO 8601)")
    acknowledged: bool = Field(default=False, description="是否已确认")


class AlarmList(BaseModel):
    """站点活跃报警列表。"""
    site_id: str = Field(..., description="站点 ID")
    total_count: int = Field(..., description="活跃报警总数")
    alarms: list[AlarmItem] = Field(default_factory=list, description="报警列表")


# ── Phase 4.2 新增工具输出模型 ─────────────────────────────────────

class CarbonInfo(BaseModel):
    """碳排信息（光伏月发电 + 碳减排）。"""
    photovoltaic_month_kwh: float = Field(..., description="本月光伏发电量 (kWh)")
    carbon_reduce_month_kg: float = Field(..., description="本月碳减排量 (kgCO₂e)")
    carbon_reduce_total_kg: float = Field(default=0.0, description="累计碳减排量 (kgCO₂e)")
    pv_mom_pct: float = Field(default=0.0, description="光伏发电环比 (%)")
    carbon_mom_pct: float = Field(default=0.0, description="碳减排环比 (%)")


class EnergyUsage(BaseModel):
    """全厂用电量（今日 + 本月 + 趋势）。"""
    today_kwh: float = Field(..., description="今日用电量 (kWh)")
    month_kwh: float = Field(..., description="本月用电量 (kWh)")
    today_mom_pct: float = Field(default=0.0, description="今日环比昨日 (%)")
    month_mom_pct: float = Field(default=0.0, description="本月环比上月 (%)")


class DeviceRank(BaseModel):
    """设备用电排名。"""
    rank_type: str = Field(..., description="排名类型: factory(全厂) / room(机房)")
    items: list[dict] = Field(default_factory=list, description="排名列表 [{name, value_kwh, proportion_pct?}]")
    room_cop_instant: Optional[float] = Field(default=None, description="机房瞬时COP（仅 rank_type=room 时返回）")
    room_cop_avg: Optional[float] = Field(default=None, description="机房累计COP（仅 rank_type=room 时返回）")


class EnvironmentParams(BaseModel):
    """室外环境参数。"""
    outdoor_temp_c: float = Field(..., description="室外温度 (°C)")
    outdoor_humidity_pct: float = Field(..., description="室外湿度 (%)")
    wet_bulb_temp_c: float = Field(..., description="湿球温度 (°C)")
    enthalpy_kj_kg: float = Field(..., description="焓值 (kJ/kg)")


class EfficiencyCalendarDay(BaseModel):
    """能效日历-日度数据。"""
    date: str = Field(..., description="日期 (YYYY-MM-DD)")
    cop: float = Field(..., description="当日 COP")
    cool_kwh: float = Field(..., description="制冷量 (kWh)")
    electricity_kwh: float = Field(..., description="用电量 (kWh)")
    is_today: bool = Field(default=False, description="是否当天")


class EfficiencyCalendarMonth(BaseModel):
    """能效日历-月度汇总。"""
    month: str = Field(..., description="月份 (YYYY-MM)")
    current_cop: float = Field(..., description="当月 COP")
    average_cop: float = Field(..., description="平均 COP")
    electricity_kwh: float = Field(..., description="用电量 (kWh)")
    cool_kwh: float = Field(..., description="制冷量 (kWh)")
    cool_price: float = Field(default=0.0, description="冷价 (元/kWh)")
    electricity_charge: float = Field(default=0.0, description="电费 (元)")
    electricity_price: float = Field(default=0.0, description="电价 (元/kWh)")
