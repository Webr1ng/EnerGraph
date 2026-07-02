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
    user_id: Optional[str] = Field(default=None, description="稳定用户 ID，用于跨会话长期偏好隔离")


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


# ── 预测（loadForecast）工具输出模型（光伏 / 冷负荷通用） ───────────

# 数据来源：福加 loadForecast 服务（POST /loadForecast/predict/realTime、
# /predict/changeRealTime、/predict/histPredict、/weather/v1/getWeather）。
# 同一服务用 energyType 区分能源类型：光伏="pv"（/analysis/pv-forecast）、
# 冷负荷="load"（/analysis/load-forecast）；两者响应结构完全一致，共用本组模型。
# 逐时点位动辄上百个，这里只给 LLM 汇总（峰值/累计/点位/时范围），
# 完整曲线由 /analysis/pv-forecast、/analysis/load-forecast 页面可视化。

class ForecastSeries(BaseModel):
    """一条预测/实际曲线汇总（不把逐时点位塞给 LLM）。

    福加 loadForecast 的 actualData/forecastData/actValue/histPreValue 均为
    ``[{ts, v}, ...]`` 逐时点序列，``v`` 单位 kW，未来或缺失点 ``v=null``。
    """
    peak_kw: Optional[float] = Field(default=None, description="峰值功率 (kW，非 null 点最大值)")
    total_kwh: Optional[float] = Field(default=None, description="累计电量 (kWh，逐时功率求和)")
    point_count: int = Field(default=0, description="原始点位数（含未来 null 点）")
    valid_count: int = Field(default=0, description="有效（非 null）点位数")
    first_ts: Optional[str] = Field(default=None, description="首个时点（归一化为 YYYY-MM-DD HH:MM:SS）")
    last_ts: Optional[str] = Field(default=None, description="末个时点")


class RealtimeForecast(BaseModel):
    """今日 / 所选日期的预测 vs 实时实际曲线（realTime / changeRealTime）。

    光伏/冷负荷页面右上小面板字段（今日平均偏差=accuracy、当前负荷=current_load_kw、
    预测负荷=predicted_load_kw、下小时预测=next_hour_forecast_kw）均在此。
    """
    actual: ForecastSeries = Field(..., description="实际曲线汇总")
    forecast: ForecastSeries = Field(..., description="预测曲线汇总")
    current_load_kw: Optional[float] = Field(default=None, description="当前实际功率 (kW)")
    predicted_load_kw: Optional[float] = Field(default=None, description="预测功率 (kW)")
    accuracy: Optional[str] = Field(default=None, description="今日平均偏差/准确率 (%)；非今日为 '-'")
    evaluation_grade: Optional[str] = Field(default=None, description="评估等级（如 '一级'）")
    next_hour_forecast_kw: Optional[float] = Field(default=None, description="下一小时预测功率 (kW)")


class HistoryForecast(BaseModel):
    """历史对比（昨日 / 上周，histPredict）。"""
    actual: ForecastSeries = Field(..., description="实际曲线汇总")
    forecast: ForecastSeries = Field(..., description="预测曲线汇总")
    accuracy: Optional[str] = Field(default=None, description="历史平均偏差/准确率 (avaccuracy)")


class WeatherEntry(BaseModel):
    """天气预报单条。日模式=逐时；周模式=每日。"""
    skycon: str = Field(default="", description="天气状况（晴/多云/阴/雨...）")
    temperature_min: Optional[float] = Field(default=None, description="日模式=该时点温度；周模式=当日最低 (°C)")
    temperature_max: Optional[float] = Field(default=None, description="日模式=null；周模式=当日最高 (°C)")
    humidity_avg: Optional[float] = Field(default=None, description="湿度 (%)；日模式=该时点，周模式=当日平均")


class ForecastResult(BaseModel):
    """预测综合查询结果（对应 /analysis/pv-forecast、/analysis/load-forecast 页面四块数据）。

    光伏（fetch_pv_forecast, energyType=pv）与冷负荷（fetch_load_forecast,
    energyType=load）共用本模型——loadForecast 服务响应结构一致，仅 energyType 不同。
    页面行为：右上角单位/日期只影响上半（selected_forecast）和中间天气；
    下半昨日/上周对比恒以今日为基准，不受 date/unit 影响。
    """
    site_id: str = Field(..., description="站点 ID")
    energy_type: str = Field(..., description="能源类型：pv（光伏）/ load（冷负荷）")
    today: str = Field(..., description="今日日期 (YYYY-MM-DD)")
    date: str = Field(..., description="查询参考日期/周起始 (YYYY-MM-DD)")
    unit: str = Field(..., description="查询粒度：day / week")
    selected_forecast: Optional[RealtimeForecast] = Field(
        default=None,
        description="所选日期/周的预测vs实际（今日=realTime 带准确率，其余=changeRealTime）",
    )
    weather: list[WeatherEntry] = Field(
        default_factory=list, description="天气预报（日=逐时温湿度，周=每日最高/最低/湿度）"
    )
    yesterday: Optional[HistoryForecast] = Field(
        default=None, description="昨日预测vs实际对比（恒以今日为基准）"
    )
    last_week: Optional[HistoryForecast] = Field(
        default=None, description="上周预测vs实际对比（恒以今日为基准）"
    )
