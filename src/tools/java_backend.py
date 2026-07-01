"""java_backend — 福加监控数据工具（COP / 能耗 / 报警 / 碳排 / 光伏 / 排名 / 环境 / 能效日历）

所属层：tools
依赖：src.schemas.action_agent, src.utils.fuca_token_refresher, httpx, os, yaml
对接算法层：N/A（对接福加 API 真实监控数据）

Phase 4.2: 所有工具接入真实 API，未配置 FUCA_API_BASE_URL 时返回 error（不返回假数据）。
Phase 4.3: Token 自动刷新 — 401 时自动调用 fuca_token_refresher 重新登录获取 Token。
"""
import logging
import os
import threading
import yaml
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from src.schemas.action_agent import (
    COPData,
    EnergySummary,
    AlarmItem,
    AlarmList,
    CarbonInfo,
    EnergyUsage,
    DeviceRank,
    EnvironmentParams,
    EfficiencyCalendarDay,
    EfficiencyCalendarMonth,
    ForecastResult,
    ForecastSeries,
    RealtimeForecast,
    HistoryForecast,
    WeatherEntry,
)

logger = logging.getLogger(__name__)

# ── 福加 API 配置（动态 Token 管理） ──────────────────────────────

FUCA_API_BASE_URL = os.getenv("FUCA_API_BASE_URL")
FUCA_TENANT_ID = os.getenv("FUCA_TENANT_ID")

# Token 动态管理：进程内缓存 + 线程锁，401 时自动刷新
_token_lock = threading.Lock()
_cached_token: Optional[str] = os.getenv("FUCA_API_TOKEN")


def _get_token() -> Optional[str]:
    """获取当前可用的 Token（优先缓存，回退环境变量）。"""
    global _cached_token
    if _cached_token is None:
        _cached_token = os.getenv("FUCA_API_TOKEN")
    return _cached_token


def _refresh_token_if_possible() -> Optional[str]:
    """尝试自动刷新 Token，成功返回新 Token，失败返回 None。

    需要 .env 中配置 FUCA_LOGIN_NAME 和 FUCA_PASSWORD。
    """
    global _cached_token
    from src.utils.fuca_token_refresher import refresh_token

    try:
        new_token = refresh_token(update_env=True)
        _cached_token = new_token
        logger.info("福加 Token 自动刷新成功")
        return new_token
    except Exception as e:
        logger.warning(f"福加 Token 自动刷新失败: {e}")
        return None

# 站点映射配置缓存
_SITE_MAPPING: Optional[Dict[str, Any]] = None


# ── 内部工具函数 ──────────────────────────────────────────────────

def _load_site_mapping() -> Dict[str, Any]:
    """加载站点映射配置（缓存）。"""
    global _SITE_MAPPING
    if _SITE_MAPPING is None:
        config_path = Path(__file__).parent.parent.parent / "config" / "site_mapping.yaml"
        with open(config_path, "r", encoding="utf-8") as f:
            _SITE_MAPPING = yaml.safe_load(f)
    return _SITE_MAPPING


def _is_mock() -> bool:
    """判断是否使用 Mock 数据（未配置 API 地址时）。"""
    return FUCA_API_BASE_URL is None


def _to_float(value: Any, default: float = 0.0) -> float:
    """None-safe float 转换：None / 空串 / 非数字 → default。

    福加 API 在设备未就绪时常返回显式 null，``float(api.get(k, d))`` 会在 key 存在
    但值为 null 时崩溃（``.get`` 返回 None 而非默认值 d）。统一用本函数兜底。

    Args:
        value: 待转换的值（可能为 None / str / int / float）
        default: 转换失败时的回退值

    Returns:
        转换后的 float，失败则返回 default
    """
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _alarm_level_str(level: Any) -> str:
    """报警级别归一化为字符串。

    福加 listRealAlarms 的 ``alarmLevel`` 是 dict（如 ``{"value":4,"code":4,"mes":"严重"}``），
    非 string。直接传给 Pydantic 的 str 字段会校验失败导致整个工具报错。

    Args:
        level: 原始 alarmLevel 值（dict / str / None）

    Returns:
        级别字符串（优先取 mes，如"严重"；dict 缺 mes 回退 code；非 dict 原样返回）
    """
    if isinstance(level, dict):
        mes = level.get("mes")
        if mes:
            return str(mes)
        code = level.get("code")
        return str(code) if code is not None else "info"
    if level is None:
        return "info"
    return str(level)


def _get_site_config(site_id: str) -> Dict[str, Any]:
    """获取站点配置，不存在时返回空字典。"""
    return _load_site_mapping().get("sites", {}).get(site_id, {})


def _headers() -> Dict[str, str]:
    """构建福加 API 公共请求头（使用动态 Token）。"""
    token = _get_token()
    return {
        "Authorization": f"Bearer {token}",
        "tenant_id": FUCA_TENANT_ID,
    }


def _api_get(path: str, params: Optional[Dict] = None) -> Dict[str, Any]:
    """福加 API GET 请求，支持 401 自动刷新 Token 并重试一次。

    Args:
        path: API 路径（如 /integrateMonitor/fucaOverviewScreen/carbonInfo）
        params: 查询参数

    Returns:
        API 响应中的 data 字段

    Raises:
        httpx.HTTPStatusError: 非 401 的 HTTP 错误
        RuntimeError: API 返回 code != 200
    """
    url = f"{FUCA_API_BASE_URL}{path}"
    resp = httpx.get(url, params=params, headers=_headers(), timeout=10)

    # 401 → 自动刷新 Token 并重试一次
    if resp.status_code == 401:
        logger.warning(f"GET {path} 返回 401，尝试自动刷新 Token...")
        with _token_lock:
            _refresh_token_if_possible()
        resp = httpx.get(url, params=params, headers=_headers(), timeout=10)

    resp.raise_for_status()
    body = resp.json()
    if body.get("code") != 200:
        # 业务层 401（部分福加 API 用 code=401 而非 HTTP 401）
        if body.get("code") == 401:
            logger.warning(f"GET {path} 返回 code=401，尝试自动刷新 Token...")
            with _token_lock:
                _refresh_token_if_possible()
            resp = httpx.get(url, params=params, headers=_headers(), timeout=10)
            resp.raise_for_status()
            body = resp.json()
            if body.get("code") != 200:
                raise RuntimeError(f"API 返回错误（刷新后重试仍失败）: {body.get('message', '未知错误')}")
        else:
            raise RuntimeError(f"API 返回错误: {body.get('message', '未知错误')}")
    return body.get("data", {})


def _api_post(path: str, json_body: Dict[str, Any]) -> Dict[str, Any]:
    """福加 API POST 请求，支持 401 自动刷新 Token 并重试一次。

    Args:
        path: API 路径
        json_body: 请求体

    Returns:
        API 响应中的 data 字段

    Raises:
        httpx.HTTPStatusError: 非 401 的 HTTP 错误
        RuntimeError: API 返回 code != 200
    """
    url = f"{FUCA_API_BASE_URL}{path}"
    resp = httpx.post(url, json=json_body, headers=_headers(), timeout=10)

    # 401 → 自动刷新 Token 并重试一次
    if resp.status_code == 401:
        logger.warning(f"POST {path} 返回 401，尝试自动刷新 Token...")
        with _token_lock:
            _refresh_token_if_possible()
        resp = httpx.post(url, json=json_body, headers=_headers(), timeout=10)

    resp.raise_for_status()
    body = resp.json()
    if body.get("code") != 200:
        if body.get("code") == 401:
            logger.warning(f"POST {path} 返回 code=401，尝试自动刷新 Token...")
            with _token_lock:
                _refresh_token_if_possible()
            resp = httpx.post(url, json=json_body, headers=_headers(), timeout=10)
            resp.raise_for_status()
            body = resp.json()
            if body.get("code") != 200:
                raise RuntimeError(f"API 返回错误（刷新后重试仍失败）: {body.get('message', '未知错误')}")
        else:
            raise RuntimeError(f"API 返回错误: {body.get('message', '未知错误')}")
    return body.get("data", {})


def _api_post_raw(path: str, json_body: Dict[str, Any]) -> Any:
    """福加 Feign 类 API 的 POST 请求，返回裸响应体（不校验 code/data 结构）。

    部分 /dataPool/feign/ 接口直接返回裸数值（如 ``2705.0``），不走标准
    ``{code, data}`` 包裹，不能用 :func:`_api_post`。本函数只做 401 自动刷新，
    不检查业务 code，原样返回解析后的 JSON（可能是 number / str / list / dict）。

    Args:
        path: API 路径
        json_body: 请求体

    Returns:
        原始响应体（JSON 解析后的值，类型不固定）

    Raises:
        httpx.HTTPStatusError: 非 401 的 HTTP 错误
    """
    url = f"{FUCA_API_BASE_URL}{path}"
    resp = httpx.post(url, json=json_body, headers=_headers(), timeout=10)

    if resp.status_code == 401:
        logger.warning(f"POST {path} 返回 401，尝试自动刷新 Token...")
        with _token_lock:
            _refresh_token_if_possible()
        resp = httpx.post(url, json=json_body, headers=_headers(), timeout=10)

    resp.raise_for_status()
    return resp.json()


def _api_post_pv(path: str, json_body: Dict[str, Any]) -> Dict[str, Any]:
    """loadForecast 专用 POST：过期 Token 触发的 HTTP 500 也刷新重试一次。

    福加 loadForecast 微服务对过期 Token 返回 HTTP 500（而非 401），通用
    :func:`_api_post` 的 401 自动刷新不会触发。本函数在 500 时复用现有
    :func:`_refresh_token_if_possible`（RSA 登录 → ``/emp-admin/auth/account/mb/token``）
    刷新后重试一次；非 500 的 HTTP 错误原样抛出，交由调用方 try-except 兜底。

    复用而非另起一套 mb-token 逻辑：``refresh_token`` 本就产出 loadForecast 所需的
    mb token，缺的只是把 500 也纳入刷新触发条件。

    Args:
        path: loadForecast 路径（如 /loadForecast/predict/realTime）
        json_body: 请求体

    Returns:
        API 响应中的 data 字段

    Raises:
        httpx.HTTPStatusError: 非 500 的 HTTP 错误，或刷新后重试仍 500
        RuntimeError: API 返回 code != 200
    """
    try:
        return _api_post(path, json_body)
    except httpx.HTTPStatusError as e:
        if e.response.status_code != 500:
            raise
        logger.warning(f"loadForecast {path} 返回 500（疑似 Token 过期），刷新后重试一次...")
        with _token_lock:
            _refresh_token_if_possible()
        return _api_post(path, json_body)


def _query_point_group_names(point_names: list, device_code: str = "") -> Dict[str, str]:
    """通用 pointGroupNames 查询（COP 和环境参数共用）。

    Args:
        point_names: 要查询的参数名列表
        device_code: 设备 code（环境参数需要，COP 不需要）

    Returns:
        {参数名: 值, ...}
    """
    body: Dict[str, Any] = {"pointGroupNames": point_names}
    if device_code:
        body["currentDeviceCode"] = device_code
    return _api_post("/integrateMonitor/chillerRoom/getValueByPointGroupNames", body)


def _query_point_efficiency(point: Dict[str, Any]) -> List[Dict[str, Any]]:
    """通用 queryPointEnergyEfficiency 查询，返回某点位当日的时间序列。

    Args:
        point: efficiency_points 中的单个条目（含 point_id/point_name/param_name/obj_name/unit）

    Returns:
        pointValues 列表（每项含 ts / v 等字段），无数据时为空列表
    """
    now = datetime.now()
    start = now.strftime("%Y-%m-%d 00:00:00")
    end = (now + timedelta(days=1)).strftime("%Y-%m-%d 00:00:00")

    api_data = _api_post("/analysisWeb/efficiencyQuery/v1/queryPointEnergyEfficiency", {
        "dimension": "day",
        "startTime": start,
        "endTime": end,
        "pointName": point["point_name"],
        "pointId": point["point_id"],
        "attrType": "I",
        "objName": point["obj_name"],
        "paramName": point["param_name"],
        "unit": point.get("unit", ""),
    })
    return api_data.get("pointValues", [])


# ── COP 数据 ──────────────────────────────────────────────────────

def fetch_cop_data(site_id: str, chiller_id: str = "CH-01") -> Dict[str, Any]:
    """获取冷水机房 COP（能效比）数据 + 机组运行参数（温度/功率）。

    组合两个真实 API:
    - getValueByPointGroupNames: 机房级 COP + 系统瞬时功率（累计=水系统平均SCOP / 瞬时=水系统瞬时SCOP / 功率=水系统瞬时功率）
    - getDeviceRunningInfo: 机组级蒸发器/冷凝器温度

    Args:
        site_id: 站点 ID（如 FJJB000001）
        chiller_id: 冷水机组编号（CH-01 或 CH-02）

    Returns:
        COPData 的 dict 表示
    """
    try:
        if _is_mock():
            return {"error": "fetch_cop_data: 未配置福加 API（FUCA_API_BASE_URL），无法获取真实数据"}
        site_config = _get_site_config(site_id)

        # 1. 获取机房级 COP + 系统瞬时功率（getValueByPointGroupNames 一次调用）
        #    累计COP ← 水系统平均SCOP；瞬时COP ← 水系统瞬时SCOP；功率 ← 水系统瞬时功率（机房总功率，非单机）
        #    历史：原从 getDeviceRunningInfo 取单机"机组实时功率"，夏季 CH-01 待机时会误报 0；
        #          改用系统级瞬时功率，反映整个冷水机房总用电。
        point_names = list(site_config.get("cop_point_names", [
            "水系统平均SCOP", "水系统瞬时SCOP"
        ]))
        if "水系统瞬时功率" not in point_names:
            point_names.append("水系统瞬时功率")
        cop_data = _query_point_group_names(point_names)
        instant_cop = _to_float(cop_data.get("水系统瞬时SCOP"))
        cumulative_cop = _to_float(cop_data.get("水系统平均SCOP"))
        power_kw = _to_float(cop_data.get("水系统瞬时功率"))

        # 2. 获取机组级运行数据（蒸发器/冷凝器温度）
        chiller_ids = site_config.get("chiller_device_ids", {})
        device_id = chiller_ids.get(chiller_id)
        chilled_water_out_temp = 0.0
        cooling_water_in_temp = 0.0

        if device_id:
            try:
                running_info = _api_post(
                    "/integrateMonitor/device/running/getDeviceRunningInfo",
                    {"deviceId": device_id}
                )
                # 解析蒸发器温度
                evaporator = running_info.get("YXSJ-ZFQ", {}).get("YXSJ-ZFQ", [])
                for item in evaporator:
                    if item.get("propertyName") == "蒸发器出水温度":
                        chilled_water_out_temp = _to_float(item.get("propertyValue"))

                # 解析冷凝器温度
                condenser = running_info.get("YXSJ-LNQ", {}).get("YXSJ-LNQ", [])
                for item in condenser:
                    if item.get("propertyName") == "冷凝器进水温度":
                        cooling_water_in_temp = _to_float(item.get("propertyValue"))
            except Exception as e:
                logger.warning(f"getDeviceRunningInfo 失败，温度字段为 0: {e}")

        return COPData(
            site_id=site_id,
            chiller_id=chiller_id,
            instant_cop=instant_cop,
            cumulative_cop=cumulative_cop,
            chilled_water_out_temp=chilled_water_out_temp,
            cooling_water_in_temp=cooling_water_in_temp,
            power_kw=power_kw,
            timestamp=datetime.now(timezone.utc).isoformat(),
            status="normal",
        ).model_dump()
    except Exception as e:
        logger.error(f"fetch_cop_data 失败: {e}")
        return {"error": f"fetch_cop_data: {e}"}


# ── 能耗汇总 ──────────────────────────────────────────────────────

def fetch_energy_summary(site_id: str, date: str = "") -> Dict[str, Any]:
    """获取站点单日能耗汇总数据。

    组合两个真实 API:
    - v1/ECInfo: 设备级用电量统计（与能耗分析页面一致）
    - supplyAndDemandList: 供需结构汇总（与前端光储实时能量页面一致，每小时粒度）

    Args:
        site_id: 站点 ID（如 FJJB000001）
        date: 统计日期，格式 YYYY-MM-DD，默认今天

    Returns:
        EnergySummary 的 dict 表示
    """
    try:
        if not date:
            date = datetime.now().strftime("%Y-%m-%d")

        if _is_mock():
            return {"error": "fetch_energy_summary: 未配置福加 API（FUCA_API_BASE_URL），无法获取真实数据"}
        site_config = _get_site_config(site_id)

        # 1. 使用 ECInfo API 获取设备级用电量（与能耗分析页面一致）
        ec_payload = {
            "nodeId": site_id,
            "nodeName": site_config["name"],
            "deviceType": site_config["device_type"],
            "classificationCode": site_config["classification_code"],
            "classificationName": site_config["classification_name"],
            "deviceName": site_config["device_name"],
            "dimension": "day",
            "startTime": f"{date} 00:00:00",
            "endTime": f"{date} 23:59:59",
            "deviceCodes": site_config["device_codes"],
            "deviceLevel": site_config["device_level"],
        }
        ec_data = _api_post("/analysisWeb/energyAnalysis/v1/ECInfo", ec_payload)

        total_consumption = _to_float(ec_data.get("totalEnergy"))
        peak_load = _to_float(ec_data.get("maxEnergy"))
        avg_load = _to_float(ec_data.get("avgEnergy"))
        carbon_coeff = _to_float(ec_data.get("carbonCoefficient"), 0.7703)

        # 2. 光伏 + 储能 + 电网交互：使用 supplyAndDemandList（每小时汇总）
        #    每小时值即为该时段能量(kWh)，24 个时点累加得日累计。
        #    供给侧：光伏发电（负值取绝对）、电网取电（正值为取电）、储能放电
        #    需求侧：储能充电、电网售电、电力负荷
        #    与前端 coordination/energy 供需结构页面数据一致。
        sd_data = _api_get(
            "/integrateMonitor/photovoltaicStorage/supplyAndDemandList",
            {"date": date}
        )
        total_pv = 0.0
        grid_import = 0.0
        storage_charge = 0.0
        storage_discharge = 0.0

        for entry in sd_data:
            for item in entry.get("supplyList", []):
                v = _to_float(item.get("value"))
                code = item.get("code")
                if code == "photovoltaic":
                    total_pv += abs(v)
                elif code == "powerGrid":
                    if v > 0:
                        grid_import += v
                elif code == "energyStorageDischarge":
                    storage_discharge += v
            for item in entry.get("demandList", []):
                code = item.get("code")
                if code == "energyStorageCharge":
                    storage_charge += _to_float(item.get("value"))

        # 碳减排 = 光伏发电量 × 0.57 kgCO₂e/kWh（国标排放因子）
        carbon_reduction = total_pv * 0.57

        return EnergySummary(
            site_id=site_id,
            date=date,
            total_consumption_kwh=total_consumption,
            pv_generation_kwh=round(total_pv, 1),
            grid_import_kwh=round(grid_import, 1),
            storage_charge_kwh=round(storage_charge, 1),
            storage_discharge_kwh=round(storage_discharge, 1),
            peak_load_kw=peak_load,
            avg_load_kw=round(avg_load, 2),
            carbon_reduction_kg=round(carbon_reduction, 2),
        ).model_dump()
    except Exception as e:
        logger.error(f"fetch_energy_summary 失败: {e}")
        return {"error": f"fetch_energy_summary: {e}"}


# ── 活跃报警 ──────────────────────────────────────────────────────

def fetch_active_alarms(site_id: str) -> Dict[str, Any]:
    """获取站点当前活跃报警列表。

    动态计算最近 N 天的时间范围（N 由 site_mapping.yaml 的 alarm_days 配置）。

    Args:
        site_id: 站点 ID

    Returns:
        AlarmList 的 dict 表示
    """
    try:
        if _is_mock():
            return {"error": "fetch_active_alarms: 未配置福加 API（FUCA_API_BASE_URL），无法获取真实数据"}
        site_config = _get_site_config(site_id)
        alarm_days = site_config.get("alarm_days", 7)
        now = datetime.now()
        start = (now - timedelta(days=alarm_days)).strftime("%Y-%m-%d 00:00:00")
        end = now.strftime("%Y-%m-%d 23:59:59")

        api_data = _api_post("/intelligentAlarm/alarm/listRealAlarms", {
            "startTime": start, "endTime": end, "pageNum": 1, "pageSize": 10,
        })
        records = api_data.get("records", [])
        alarms = [
            AlarmItem(
                alarm_id=str(r.get("alarmInfoId", r.get("id", f"ALM-{i}"))),
                level=_alarm_level_str(r.get("alarmLevel")),
                device=r.get("deviceName", "未知设备"),
                message=r.get("alarmContent", r.get("alarmName", "未知报警")),
                timestamp=r.get("firstTime", r.get("alarmTime", datetime.now(timezone.utc).isoformat())),
                acknowledged=r.get("recoverTime") is not None,
            )
            for i, r in enumerate(records)
        ]
        return AlarmList(
            site_id=site_id,
            total_count=api_data.get("total", 0),
            alarms=alarms,
        ).model_dump()
    except Exception as e:
        logger.error(f"fetch_active_alarms 失败: {e}")
        return {"error": f"fetch_active_alarms: {e}"}


# ── 月度报警统计（实时 + 历史合计） ─────────────────────────────

def fetch_monthly_alarm_count(site_id: str, date: str = "") -> Dict[str, Any]:
    """获取指定月份的报警总数（实时报警 + 历史报警的 total 累加）。

    同时调用两个 API:
    - /intelligentAlarm/alarm/listRealAlarms（实时报警）
    - /intelligentAlarm/alarm/listHisAlarms（历史报警）
    取两者 total 字段的累加和。

    Args:
        site_id: 站点 ID
        date: 查询月份，格式 YYYY-MM，默认当月

    Returns:
        dict: {month, real_count, history_count, total_count}
    """
    try:
        if not date:
            date = datetime.now().strftime("%Y-%m")

        if _is_mock():
            return {"error": "fetch_monthly_alarm_count: 未配置福加 API（FUCA_API_BASE_URL），无法获取真实数据"}

        from calendar import monthrange
        year, month = map(int, date.split("-"))
        _, last_day = monthrange(year, month)
        start_time = f"{date}-01 00:00:00"
        end_time = f"{date}-{last_day:02d} 23:59:59"

        common_params: Dict[str, Any] = {
            "startTime": start_time,
            "endTime": end_time,
            "pageNum": 1,
            "pageSize": 10,
        }

        # 两个接口都是 POST（GET 返回 405），响应走标准 {code, data} 包裹，
        # data 内含 total 字段。_api_post 自带 401 自动刷新。
        real_data = _api_post("/intelligentAlarm/alarm/listRealAlarms", common_params)
        his_data = _api_post("/intelligentAlarm/alarm/listHisAlarms", common_params)

        real_count = real_data.get("total", 0) if isinstance(real_data, dict) else 0
        his_count = his_data.get("total", 0) if isinstance(his_data, dict) else 0

        return {
            "month": date,
            "real_count": real_count,
            "history_count": his_count,
            "total_count": real_count + his_count,
        }
    except Exception as e:
        logger.error(f"fetch_monthly_alarm_count 失败: {e}")
        return {"error": f"fetch_monthly_alarm_count: {e}"}


# ── 碳排信息（光伏月发电 + 碳减排） ──────────────────────────────

def fetch_carbon_info(site_id: str) -> Dict[str, Any]:
    """获取碳排信息：本月光伏发电量、碳减排量、累计碳减排、环比数据。

    Args:
        site_id: 站点 ID

    Returns:
        CarbonInfo 的 dict 表示
    """
    try:
        if _is_mock():
            return {"error": "fetch_carbon_info: 未配置福加 API（FUCA_API_BASE_URL），无法获取真实数据"}
        api_data = _api_get("/integrateMonitor/fucaOverviewScreen/carbonInfo")
        return CarbonInfo(
            photovoltaic_month_kwh=_to_float(api_data.get("photovoltaicMonth")),
            carbon_reduce_month_kg=_to_float(api_data.get("carbonReduceMonth")),
            carbon_reduce_total_kg=_to_float(api_data.get("carbonReduceTotal")),
            pv_mom_pct=_to_float(api_data.get("photovoltaicMonthMoM")),
            carbon_mom_pct=_to_float(api_data.get("carbonReduceMonthMoM")),
        ).model_dump()
    except Exception as e:
        logger.error(f"fetch_carbon_info 失败: {e}")
        return {"error": f"fetch_carbon_info: {e}"}


# ── 光伏月度数据（发电量 + 收益） ─────────────────────────────────

def fetch_photovoltaic_monthly(site_id: str) -> Dict[str, Any]:
    """获取光伏月度发电量和收益明细（按月列表）。

    真实 API: GET /integrateMonitor/fucaOverviewScreen/photovoltaicList

    Args:
        site_id: 站点 ID

    Returns:
        dict: {months: [{month, generation_kwh, earnings_yuan}, ...]}
    """
    try:
        if _is_mock():
            return {"error": "fetch_photovoltaic_monthly: 未配置福加 API（FUCA_API_BASE_URL），无法获取真实数据"}
        api_data = _api_get("/integrateMonitor/fucaOverviewScreen/photovoltaicList")
        months = []
        for item in api_data:
            gen = next((x["value"] for x in item.get("list", []) if x["code"] == "discharge"), 0)
            earn = next((x["value"] for x in item.get("list", []) if x["code"] == "earnings"), 0)
            months.append({"month": item["ts"], "generation_kwh": _to_float(gen), "earnings_yuan": _to_float(earn)})
        return {"months": months}
    except Exception as e:
        logger.error(f"fetch_photovoltaic_monthly 失败: {e}")
        return {"error": f"fetch_photovoltaic_monthly: {e}"}


# ── 日度光伏发电量 ─────────────────────────────────────────────────

def fetch_photovoltaic_daily(site_id: str, date: str = "") -> Dict[str, Any]:
    """获取指定日期的光伏发电量。

    真实 API: GET /integrateMonitor/photovoltaicStorage/supplyAndDemandList
    每小时汇总光伏发电量（与前端供需结构页面一致），累加 24 个时点得日发电量。

    Args:
        site_id: 站点 ID
        date: 查询日期，格式 YYYY-MM-DD，默认今天

    Returns:
        dict: {date, generation_kwh, peak_power_kw, data_points}
    """
    try:
        if not date:
            date = datetime.now().strftime("%Y-%m-%d")

        if _is_mock():
            return {"error": "fetch_photovoltaic_daily: 未配置福加 API（FUCA_API_BASE_URL），无法获取真实数据"}
        api_data = _api_get("/integrateMonitor/photovoltaicStorage/supplyAndDemandList", {
            "date": date,
        })

        total_kwh = 0.0
        peak_kw = 0.0
        count = 0
        for entry in api_data:
            for item in entry.get("supplyList", []):
                if item.get("code") == "photovoltaic":
                    power = abs(_to_float(item.get("value")))  # 发电为负值取绝对
                    total_kwh += power
                    peak_kw = max(peak_kw, power)
                    count += 1
                    break

        return {
            "date": date,
            "generation_kwh": round(total_kwh, 1),
            "peak_power_kw": round(peak_kw, 1),
            "data_points": count,
        }
    except Exception as e:
        logger.error(f"fetch_photovoltaic_daily 失败: {e}")
        return {"error": f"fetch_photovoltaic_daily: {e}"}


# ── 全厂用电量（今日 + 本月） ─────────────────────────────────────

def fetch_energy_usage(site_id: str) -> Dict[str, Any]:
    """获取全厂用电量：今日用电、本月用电。

    使用两个 Feign 接口（与前端首页同源，返回裸数值）:
    - POST /dataPool/feign/indicator/tenantTotalECDay → 裸数值（今日用电量 kWh）
    - POST /dataPool/feign/indicator/tenantTotalECMonth → 裸数值（本月用电量 kWh）

    Args:
        site_id: 站点 ID

    Returns:
        EnergyUsage 的 dict 表示
    """
    try:
        if _is_mock():
            return {"error": "fetch_energy_usage: 未配置福加 API（FUCA_API_BASE_URL），无法获取真实数据"}

        today = datetime.now().strftime("%Y-%m-%d")
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

        # 今日用电（Feign 接口直接返回裸数值，如 2705.0）
        today_value = _api_post_raw("/dataPool/feign/indicator/tenantTotalECDay", {
            "tenantId": 1071,
            "startTime": f"{today} 00:00:00",
            "endTime": f"{tomorrow} 00:00:00",
        })
        today_kwh = _to_float(today_value)

        # 本月用电（同上，裸数值，如 130668.8）
        month = datetime.now().strftime("%Y-%m")
        month_value = _api_post_raw("/dataPool/feign/indicator/tenantTotalECMonth", {
            "tenantId": 1071,
            "startTime": f"{month}-01 00:00:00",
            "endTime": f"{tomorrow} 00:00:00",
        })
        month_kwh = _to_float(month_value)

        return EnergyUsage(
            today_kwh=today_kwh,
            month_kwh=month_kwh,
        ).model_dump()
    except Exception as e:
        logger.error(f"fetch_energy_usage 失败: {e}")
        return {"error": f"fetch_energy_usage: {e}"}


# ── 设备用电排名 ──────────────────────────────────────────────────

def fetch_device_rank(site_id: str, rank_type: str = "factory") -> Dict[str, Any]:
    """获取设备用电排名。

    rank_type="factory": 全厂设备排名 Top5（GET deviceEnergyRankTop5Month）
    rank_type="room": 机房设备排名（GET cockpit/roomEnergy，含 COP）

    Args:
        site_id: 站点 ID
        rank_type: "factory"（全厂）或 "room"（机房）

    Returns:
        DeviceRank 的 dict 表示
    """
    try:
        if _is_mock():
            return {"error": "fetch_device_rank: 未配置福加 API（FUCA_API_BASE_URL），无法获取真实数据"}
        if rank_type == "room":
            site_config = _get_site_config(site_id)
            api_data = _api_get("/integrateMonitor/cockpit/roomEnergy", {
                "deviceId": site_config.get("cwer_id", 3602),
                "deviceCode": site_config.get("cwer_device_code", "KTXT-CWER-0001"),
            })
            items = [
                {"name": d["name"], "value_kwh": _to_float(d["value"]), "proportion_pct": _to_float(d["prop"])}
                for d in api_data.get("deviceEnergyList", [])
            ]
            return DeviceRank(
                rank_type=rank_type,
                items=items,
                room_cop_instant=_to_float(api_data.get("copInstant")),
                room_cop_avg=_to_float(api_data.get("copAvg")),
            ).model_dump()
        else:
            api_data = _api_get("/integrateMonitor/energyMonitor/v1/deviceEnergyRankTop5Month")
            items = sorted(
                [{"name": name, "value_kwh": _to_float(value)} for name, value in api_data.items()],
                key=lambda x: x["value_kwh"], reverse=True,
            )
            return DeviceRank(rank_type=rank_type, items=items).model_dump()
    except Exception as e:
        logger.error(f"fetch_device_rank 失败: {e}")
        return {"error": f"fetch_device_rank: {e}"}


# ── 环境参数 ──────────────────────────────────────────────────────

def fetch_environment_params(site_id: str) -> Dict[str, Any]:
    """获取室外环境参数：温度、湿度、湿球温度、焓值。

    与 COP 共用 pointGroupNames 接口。

    Args:
        site_id: 站点 ID

    Returns:
        EnvironmentParams 的 dict 表示
    """
    try:
        if _is_mock():
            return {"error": "fetch_environment_params: 未配置福加 API（FUCA_API_BASE_URL），无法获取真实数据"}
        site_config = _get_site_config(site_id)
        point_names = site_config.get("env_point_names", [
            "室外温度", "室外湿度", "室外湿球温度", "室外焓值"
        ])
        device_code = site_config.get("cwer_device_code", "KTXT-CWER-0001")
        api_data = _query_point_group_names(point_names, device_code)
        return EnvironmentParams(
            outdoor_temp_c=_to_float(api_data.get("室外温度")),
            outdoor_humidity_pct=_to_float(api_data.get("室外湿度")),
            wet_bulb_temp_c=_to_float(api_data.get("室外湿球温度")),
            enthalpy_kj_kg=_to_float(api_data.get("室外焓值")),
        ).model_dump()
    except Exception as e:
        logger.error(f"fetch_environment_params 失败: {e}")
        return {"error": f"fetch_environment_params: {e}"}


# ── 能效日历 ──────────────────────────────────────────────────────

def fetch_efficiency_calendar(site_id: str, date: str = "", mode: str = "day") -> Dict[str, Any]:
    """获取能效日历数据（日度或月度）。

    mode="day": 当月每天的 COP / 制冷量 / 用电量
    mode="month": 月度汇总（COP / 制冷量 / 电费 / 电价）

    Args:
        site_id: 站点 ID
        date: 查询月份，格式 YYYY-MM，默认当月
        mode: "day" 或 "month"

    Returns:
        日度: {month, days: [EfficiencyCalendarDay, ...]}
        月度: EfficiencyCalendarMonth 的 dict
    """
    try:
        if not date:
            date = datetime.now().strftime("%Y-%m")

        if _is_mock():
            return {"error": "fetch_efficiency_calendar: 未配置福加 API（FUCA_API_BASE_URL），无法获取真实数据"}
        site_config = _get_site_config(site_id)
        cwer_id = site_config.get("cwer_id", 3602)

        if mode == "month":
            api_data = _api_get("/analysisWeb/EfficiencyCalendar/queryCOP", {
                "date": date, "cwerId": cwer_id,
            })
            return EfficiencyCalendarMonth(
                month=date,
                current_cop=_to_float(api_data.get("currentCOP")),
                average_cop=_to_float(api_data.get("averageCOP")),
                electricity_kwh=_to_float(api_data.get("electricity")),
                cool_kwh=_to_float(api_data.get("cool")),
                cool_price=_to_float(api_data.get("coolPrice")),
                electricity_charge=_to_float(api_data.get("echarge")),
                electricity_price=_to_float(api_data.get("eprice")),
            ).model_dump()
        else:
            api_data = _api_get("/analysisWeb/EfficiencyCalendar/queryCalendar", {
                "date": date, "cwerId": cwer_id,
            })
            days = [
                EfficiencyCalendarDay(
                    date=r.get("date", ""),
                    cop=_to_float(r.get("cop")),
                    cool_kwh=_to_float(r.get("cool")),
                    electricity_kwh=_to_float(r.get("electricity")),
                    is_today=r.get("nowDay", False),
                ).model_dump()
                for r in api_data
            ]
            return {"month": date, "days": days}
    except Exception as e:
        logger.error(f"fetch_efficiency_calendar 失败: {e}")
        return {"error": f"fetch_efficiency_calendar: {e}"}


# ── 能效查询通用详情 ──────────────────────────────────────────────

def fetch_efficiency_detail(site_id: str, param_name: str = "水系统平均COP") -> Dict[str, Any]:
    """通用能效查询：按参数名查询任意能效指标的时间序列。

    真实 API: POST /analysisWeb/efficiencyQuery/v1/queryPointEnergyEfficiency
    通过 site_mapping.yaml 的 efficiency_points 目录解析 param_name → pointId。

    可用 param_name:
      水系统平均COP, 冷水主机平均COP, 水系统平均SCOP, 水系统瞬时SCOP,
      水系统瞬时制冷量, 水系统累计制冷量,
      水系统瞬时功率, 水系统累计电能, 水系统热平衡系数

    Args:
        site_id: 站点 ID
        param_name: 查询参数名（见上方列表）

    Returns:
        dict: {param_name, unit, current_value, latest_time, time_series_count}
        若 param_name 不在目录中，返回 error 并列出可用参数。
    """
    try:
        site_config = _get_site_config(site_id)
        points = site_config.get("efficiency_points", {})

        if param_name not in points:
            available = list(points.keys())
            return {"error": f"未知参数: {param_name}。可用参数: {', '.join(available)}"}

        point = points[param_name]

        if _is_mock():
            return {"error": "fetch_efficiency_detail: 未配置福加 API（FUCA_API_BASE_URL），无法获取真实数据"}

        values = _query_point_efficiency(point)
        current = _to_float(values[-1].get("v")) if values else 0.0
        latest_ts = values[-1].get("ts", "") if values else ""

        return {
            "param_name": param_name,
            "unit": point.get("unit", ""),
            "current_value": current,
            "latest_time": latest_ts,
            "time_series_count": len(values),
        }
    except Exception as e:
        logger.error(f"fetch_efficiency_detail 失败: {e}")
        return {"error": f"fetch_efficiency_detail: {e}"}


# ── 多日能耗汇总（Phase 6 导出） ───────────────────────────────────

def fetch_energy_range(site_id: str, start_date: str = "", end_date: str = "") -> Dict[str, Any]:
    """获取站点多日能耗汇总（逐日复用 fetch_energy_summary）。

    用于数据导出场景：用户问「最近N天能耗数据并导出」时，先取多日数据，
    再由 LLM 调用 export_data_table 生成 CSV。日期范围由 LLM 解析「最近N天」
    得出（YYYY-MM-DD）；未传时默认最近 7 天（含今天）。

    Args:
        site_id: 站点 ID（如 FJJB000001）
        start_date: 起始日期 YYYY-MM-DD，默认今天往前推 6 天
        end_date: 结束日期 YYYY-MM-DD，默认今天

    Returns:
        dict: {site_id, start_date, end_date, items: [EnergySummary dict, ...], total_days}
        单日获取失败的日期跳过，不计入 items。
    """
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        if not end_date:
            end_date = today
        if not start_date:
            start_date = (datetime.now() - timedelta(days=6)).strftime("%Y-%m-%d")

        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError as e:
            return {"error": f"fetch_energy_range: 日期格式应为 YYYY-MM-DD: {e}"}

        if start_dt > end_dt:
            start_date, end_date = end_date, start_date
            start_dt, end_dt = end_dt, start_dt

        if _is_mock():
            return {"error": "fetch_energy_range: 未配置福加 API（FUCA_API_BASE_URL），无法获取真实数据"}

        items: List[Dict[str, Any]] = []
        cur = start_dt
        while cur <= end_dt:
            day_str = cur.strftime("%Y-%m-%d")
            day_result = fetch_energy_summary(site_id, day_str)
            if isinstance(day_result, dict) and "error" not in day_result:
                items.append(day_result)
            else:
                logger.warning(f"fetch_energy_range: 跳过 {day_str}（获取失败）")
            cur += timedelta(days=1)

        return {
            "site_id": site_id,
            "start_date": start_date,
            "end_date": end_date,
            "items": items,
            "total_days": len(items),
        }
    except Exception as e:
        logger.error(f"fetch_energy_range 失败: {e}")
        return {"error": f"fetch_energy_range: {e}"}


# ── 历史报警明细（Phase 6 导出） ───────────────────────────────────

def fetch_alarm_history(site_id: str, start_date: str = "", end_date: str = "") -> Dict[str, Any]:
    """获取站点历史报警明细（按日期范围）。

    复用 listHisAlarms 接口（与 fetch_monthly_alarm_count 同源），按日期范围
    取明细记录，供 LLM 调用 export_data_table 导出报警报表。字段解析复用
    fetch_active_alarms 的 alarmLevel/firstTime/recoverTime 映射。

    Args:
        site_id: 站点 ID
        start_date: 起始日期 YYYY-MM-DD，默认今天往前推 6 天
        end_date: 结束日期 YYYY-MM-DD，默认今天

    Returns:
        dict: {site_id, start_date, end_date, items: [AlarmItem dict, ...], total}
    """
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        if not end_date:
            end_date = today
        if not start_date:
            start_date = (datetime.now() - timedelta(days=6)).strftime("%Y-%m-%d")

        try:
            datetime.strptime(start_date, "%Y-%m-%d")
            datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError as e:
            return {"error": f"fetch_alarm_history: 日期格式应为 YYYY-MM-DD: {e}"}

        if _is_mock():
            return {"error": "fetch_alarm_history: 未配置福加 API（FUCA_API_BASE_URL），无法获取真实数据"}

        start_time = f"{start_date} 00:00:00"
        end_time = f"{end_date} 23:59:59"

        api_data = _api_post("/intelligentAlarm/alarm/listHisAlarms", {
            "startTime": start_time,
            "endTime": end_time,
            "pageNum": 1,
            "pageSize": 100,
        })
        records = api_data.get("records", []) if isinstance(api_data, dict) else []
        alarms = [
            AlarmItem(
                alarm_id=str(r.get("alarmInfoId", r.get("id", f"ALM-{i}"))),
                level=_alarm_level_str(r.get("alarmLevel")),
                device=r.get("deviceName", "未知设备"),
                message=r.get("alarmContent", r.get("alarmName", "未知报警")),
                timestamp=r.get("firstTime", r.get("alarmTime", datetime.now(timezone.utc).isoformat())),
                acknowledged=r.get("recoverTime") is not None,
            ).model_dump()
            for i, r in enumerate(records)
        ]
        return {
            "site_id": site_id,
            "start_date": start_date,
            "end_date": end_date,
            "items": alarms,
            "total": len(alarms),
        }
    except Exception as e:
        logger.error(f"fetch_alarm_history 失败: {e}")
        return {"error": f"fetch_alarm_history: {e}"}


# ── 光伏预测（今日/昨日/上周 预测vs实际 + 天气） ───────────────────
# 真实 API: 福加 loadForecast 服务（POST，Bearer Token + tenant_id 头）
#   /loadForecast/predict/realTime       今日实时预测（actualData/forecastData + 准确率/等级/下一小时）
#   /loadForecast/predict/changeRealTime 所选日期/周的预测vs实际曲线（type=day|week）
#   /loadForecast/weather/v1/getWeather  天气（日=逐时温湿度；周=每日最高/最低/湿度）
#   /loadForecast/predict/histPredict    历史对比（昨日=单日；上周=7日范围），恒以今日为基准
# 请求体统一 {"startTime","endTime","type","energyType":"pv"}，tenant_id 走请求头（_headers）。
# 与 fetch_photovoltaic_daily 区别：本工具查「预测 vs 实际 + 准确率 + 天气」，
#   实际发电量/收益仍用 fetch_photovoltaic_daily（/coordination/energy）。

# 光伏预测数据用 UTC+8（福加平台时区）解释 epoch 毫秒时间戳
_PV_TZ = timezone(timedelta(hours=8))


def _opt_float(value: Any) -> Optional[float]:
    """None 透传的 float 转换。

    与 :func:`_to_float` 区别：``None`` 原样返回而非回退 ``0.0``，用于可选指标字段
    （currentLoad/predictedLoad/temperatureMax 等），避免把「未出」误报成 0。

    Args:
        value: 原始值（可能为 None / str / int / float）

    Returns:
        float 或 None
    """
    if value is None:
        return None
    return _to_float(value)


def _pv_ts_to_str(ts: Any) -> str:
    """归一化 loadForecast 时点 ts 为可读字符串。

    福加 loadForecast 的 ``ts`` 混用两种格式：epoch 毫秒字符串（如 ``"1782748800000"``，
    过去时点）和 ``"YYYY-MM-DD HH:MM:SS"`` 字符串（未来 null 点）。统一转成后者，
    epoch 按 UTC+8（平台时区）解释。

    Args:
        ts: 原始 ts 值

    Returns:
        ``YYYY-MM-DD HH:MM:SS`` 字符串；``None`` 或解析失败原样返回
    """
    if ts is None:
        return ""
    s = str(ts)
    if s.isdigit() and len(s) >= 13:
        try:
            return datetime.fromtimestamp(int(s) / 1000, tz=_PV_TZ).strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, OSError, OverflowError):
            return s
    return s


def _pv_series(points: Any) -> ForecastSeries:
    """从 ``[{ts, v}, ...]`` 逐时点序列计算峰值/累计/点位/时范围汇总（光伏/冷负荷通用）。

    ``v`` 为 ``None``（未来或缺失）的点不计入峰值/累计，但计入 ``point_count``；
    ``valid_count`` 反映实际有数据的时点数（今日实际曲线常只到当前小时，
    之后为 null，``valid_count < point_count`` 即说明数据未出全）。

    Args:
        points: loadForecast 返回的 ``actualData``/``forecastData``/``actValue``/``histPreValue``

    Returns:
        ForecastSeries 汇总
    """
    pts = points if isinstance(points, list) else []
    valid_vals: List[float] = []
    for p in pts:
        if isinstance(p, dict) and p.get("v") is not None:
            valid_vals.append(_to_float(p.get("v")))
    peak = max(valid_vals) if valid_vals else None
    total = round(sum(valid_vals), 2) if valid_vals else None
    first_ts = _pv_ts_to_str(pts[0].get("ts")) if pts and isinstance(pts[0], dict) else None
    last_ts = _pv_ts_to_str(pts[-1].get("ts")) if pts and isinstance(pts[-1], dict) else None
    return ForecastSeries(
        peak_kw=round(peak, 2) if peak is not None else None,
        total_kwh=total,
        point_count=len(pts),
        valid_count=len(valid_vals),
        first_ts=first_ts,
        last_ts=last_ts,
    )


def _build_pv_realtime(data: Dict[str, Any]) -> RealtimeForecast:
    """realTime / changeRealTime 响应 → RealtimeForecast（光伏/冷负荷通用）。"""
    return RealtimeForecast(
        actual=_pv_series(data.get("actualData")),
        forecast=_pv_series(data.get("forecastData")),
        current_load_kw=_opt_float(data.get("currentLoad")),
        predicted_load_kw=_opt_float(data.get("predictedLoad")),
        accuracy=str(data.get("accuracy")) if data.get("accuracy") is not None else None,
        evaluation_grade=str(data.get("evaluationGrade")) if data.get("evaluationGrade") is not None else None,
        next_hour_forecast_kw=_opt_float(data.get("nextHourFL")),
    )


def _build_pv_history(data: Dict[str, Any]) -> HistoryForecast:
    """histPredict 响应 → HistoryForecast（光伏/冷负荷通用）。"""
    return HistoryForecast(
        actual=_pv_series(data.get("actValue")),
        forecast=_pv_series(data.get("histPreValue")),
        accuracy=str(data.get("avaccuracy")) if data.get("avaccuracy") is not None else None,
    )


def _build_pv_weather(data: Any) -> List[WeatherEntry]:
    """getWeather 响应（数组）→ WeatherEntry 列表（光伏/冷负荷通用）。"""
    if not isinstance(data, list):
        return []
    entries: List[WeatherEntry] = []
    for w in data:
        if not isinstance(w, dict):
            continue
        entries.append(
            WeatherEntry(
                skycon=str(w.get("skycon")) if w.get("skycon") is not None else "",
                temperature_min=_opt_float(w.get("temperatureMin")),
                temperature_max=_opt_float(w.get("temperatureMax")),
                humidity_avg=_opt_float(w.get("humidityAvg")),
            )
        )
    return entries


def _fetch_loadforecast(site_id: str, date: str, unit: str, energy_type: str, tool_name: str) -> Dict[str, Any]:
    """光伏/冷负荷预测共享核心（福加 loadForecast 接口）。

    一次返回预测页面四块数据：所选日期/周的预测vs实际曲线 + 天气预报 + 昨日对比 +
    上周对比。今日查询额外带平均偏差/等级/当前负荷/预测负荷/下一小时预测。

    页面行为对齐：右上角单位/日期只影响上半曲线和中间天气；下半昨日/上周对比
    恒以今日为基准（昨日=今天-1，上周=本周一往前推一周的周一~周日），不受 date/unit 影响。

    光伏（/analysis/pv-forecast, energyType=pv）、冷负荷（/analysis/load-forecast,
    energyType=load）与电负荷（/analysis/electricity-forecast, energyType=electricity）
    走同一 loadForecast 服务、同一响应结构，仅 energyType 不同。

    Args:
        site_id: 站点 ID（如 FJJB000001）
        date: 参考日期 YYYY-MM-DD（已归一化，空=今天）
        unit: 查询粒度 ``"day"`` 或 ``"week"``（已归一化小写）
        energy_type: ``"pv"``（光伏）/ ``"load"``（冷负荷）/ ``"electricity"``（电负荷）
        tool_name: 调用方工具名，用于错误前缀（fetch_pv_forecast / fetch_load_forecast / fetch_electricity_forecast）

    Returns:
        ForecastResult 的 dict 表示；失败返回 ``{"error": f"{tool_name}: ..."}``
    """
    try:
        today_dt = datetime.now().date()
        today = today_dt.strftime("%Y-%m-%d")
        if not date:
            date = today
        unit = (unit or "day").lower()
        if unit not in ("day", "week"):
            return {"error": f"{tool_name}: unit 只能是 day 或 week，收到 {unit}"}

        try:
            ref_dt = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError as e:
            return {"error": f"{tool_name}: 日期格式应为 YYYY-MM-DD: {e}"}

        if _is_mock():
            return {"error": f"{tool_name}: 未配置福加 API（FUCA_API_BASE_URL），无法获取真实数据"}

        # 所选日期/周的起止
        if unit == "day":
            sel_start, sel_end = date, date
        else:
            monday = ref_dt - timedelta(days=ref_dt.weekday())
            sel_start = monday.strftime("%Y-%m-%d")
            sel_end = (monday + timedelta(days=6)).strftime("%Y-%m-%d")

        # 1) 上半曲线：今日→realTime（带平均偏差/等级/当前/预测/下小时），其余→changeRealTime
        if date == today and unit == "day":
            rt = _api_post_pv("/loadForecast/predict/realTime", {
                "startTime": today, "endTime": today, "type": "day", "energyType": energy_type,
            })
            selected_forecast = _build_pv_realtime(rt)
        else:
            rt = _api_post_pv("/loadForecast/predict/changeRealTime", {
                "startTime": sel_start, "endTime": sel_end, "type": unit, "energyType": energy_type,
            })
            selected_forecast = _build_pv_realtime(rt)

        # 2) 中间天气：随所选日期/单位变化
        weather_data = _api_post_pv("/loadForecast/weather/v1/getWeather", {
            "startTime": sel_start, "endTime": sel_end, "type": unit, "energyType": energy_type,
        })
        weather = _build_pv_weather(weather_data)

        # 3) 下半-昨日对比（恒以今日为基准，不受 date/unit 影响）
        yesterday = (today_dt - timedelta(days=1)).strftime("%Y-%m-%d")
        yest = _api_post_pv("/loadForecast/predict/histPredict", {
            "startTime": yesterday, "endTime": yesterday, "type": "day", "energyType": energy_type,
        })
        yesterday_forecast = _build_pv_history(yest)

        # 4) 下半-上周对比（恒以今日为基准：上周周一~周日）
        last_monday = today_dt - timedelta(days=today_dt.weekday()) - timedelta(weeks=1)
        last_sunday = last_monday + timedelta(days=6)
        lw = _api_post_pv("/loadForecast/predict/histPredict", {
            "startTime": last_monday.strftime("%Y-%m-%d"),
            "endTime": last_sunday.strftime("%Y-%m-%d"),
            "type": "day", "energyType": energy_type,
        })
        last_week_forecast = _build_pv_history(lw)

        return ForecastResult(
            site_id=site_id,
            energy_type=energy_type,
            today=today,
            date=sel_start,
            unit=unit,
            selected_forecast=selected_forecast,
            weather=weather,
            yesterday=yesterday_forecast,
            last_week=last_week_forecast,
        ).model_dump()
    except Exception as e:
        logger.error(f"{tool_name} 失败: {e}")
        return {"error": f"{tool_name}: {e}"}


def fetch_pv_forecast(site_id: str, date: str = "", unit: str = "day") -> Dict[str, Any]:
    """获取光伏预测数据（福加 loadForecast 接口，energyType=pv，对应 /analysis/pv-forecast）。

    一次返回页面四块数据：所选日期/周的预测vs实际曲线 + 天气预报 + 昨日对比 + 上周对比。
    今日查询额外带平均偏差/等级/当前负荷/预测负荷/下一小时预测。

    Args:
        site_id: 站点 ID（如 FJJB000001）
        date: 参考日期 YYYY-MM-DD，默认今天；unit=week 时传该周内任意一天，
            工具自动取周一~周日
        unit: 查询粒度 ``"day"``（默认）或 ``"week"``

    Returns:
        ForecastResult 的 dict 表示（energy_type="pv"）；失败返回 ``{"error": "fetch_pv_forecast: ..."}``
    """
    return _fetch_loadforecast(site_id, date, unit, energy_type="pv", tool_name="fetch_pv_forecast")


def fetch_load_forecast(site_id: str, date: str = "", unit: str = "day") -> Dict[str, Any]:
    """获取冷负荷预测数据（福加 loadForecast 接口，energyType=load，对应 /analysis/load-forecast）。

    与 :func:`fetch_pv_forecast` 同一 loadForecast 服务、同一响应结构，仅 energyType="load"。
    冷负荷页面比光伏多一个左上小面板（今日平均偏差 / 当前负荷 / 预测负荷 / 下小时预测），
    这些字段已在 selected_forecast（accuracy / current_load_kw / predicted_load_kw /
    next_hour_forecast_kw）中返回。

    Args:
        site_id: 站点 ID（如 FJJB000001）
        date: 参考日期 YYYY-MM-DD，默认今天；unit=week 时传该周内任意一天，
            工具自动取周一~周日
        unit: 查询粒度 ``"day"``（默认）或 ``"week"``

    Returns:
        ForecastResult 的 dict 表示（energy_type="load"）；失败返回 ``{"error": "fetch_load_forecast: ..."}``
    """
    return _fetch_loadforecast(site_id, date, unit, energy_type="load", tool_name="fetch_load_forecast")


# ── 光伏/冷负荷预测多日汇总（Phase 6 导出） ──────────────────────────

# 单次范围查询最多 31 天（每日 1 次 loadForecast 调用，避免大范围拖慢导出）
_FORECAST_RANGE_MAX_DAYS = 31


def _flatten_forecast_day(day_str: str, sf: RealtimeForecast) -> Dict[str, Any]:
    """将单日 RealtimeForecast 扁平化为导出表格的一行。

    只取 selected_forecast 的汇总指标（预测/实际峰值与累计、点位、准确率、等级、
    当前/预测/下小时负荷）；昨日/上周对比与天气与多日导出无关，不纳入。

    Args:
        day_str: 日期 YYYY-MM-DD
        sf: 单日 RealtimeForecast 模型（realTime/changeRealTime 构建结果）

    Returns:
        扁平行字典，键即 CSV 列 key
    """
    return {
        "date": day_str,
        "forecast_peak_kw": sf.forecast.peak_kw,
        "forecast_total_kwh": sf.forecast.total_kwh,
        "forecast_point_count": sf.forecast.point_count,
        "forecast_valid_count": sf.forecast.valid_count,
        "actual_peak_kw": sf.actual.peak_kw,
        "actual_total_kwh": sf.actual.total_kwh,
        "actual_point_count": sf.actual.point_count,
        "actual_valid_count": sf.actual.valid_count,
        "accuracy": sf.accuracy,
        "evaluation_grade": sf.evaluation_grade,
        "current_load_kw": sf.current_load_kw,
        "predicted_load_kw": sf.predicted_load_kw,
        "next_hour_forecast_kw": sf.next_hour_forecast_kw,
    }


def _fetch_loadforecast_range(
    site_id: str,
    start_date: str,
    end_date: str,
    energy_type: str,
    tool_name: str,
) -> Dict[str, Any]:
    """光伏/冷负荷预测多日汇总（逐日复用 loadForecast realTime/changeRealTime）。

    用于数据导出：用户问「导出最近N天光伏预测/冷负荷预测」时，先取多日预测vs实际
    汇总，再由 LLM 调用 export_data_table 生成 CSV。每日只调一个接口（今日 realTime、
    其余 changeRealTime），不复用 _fetch_loadforecast 的 weather/histPredict——
    多日导出只需 selected_forecast 的峰值/累计/准确率，避免 4×N 次 API 浪费。

    Args:
        site_id: 站点 ID（如 FJJB000001）
        start_date: 起始日期 YYYY-MM-DD，默认今天往前推 6 天
        end_date: 结束日期 YYYY-MM-DD，默认今天
        energy_type: ``"pv"``（光伏）/ ``"load"``（冷负荷）/ ``"electricity"``（电负荷）
        tool_name: 调用方工具名，用于错误前缀

    Returns:
        dict: ``{site_id, start_date, end_date, energy_type, items: [flat day row], total_days}``；
        单日获取失败的日期跳过；失败返回 ``{"error": f"{tool_name}: ..."}``
    """
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        if not end_date:
            end_date = today
        if not start_date:
            start_date = (datetime.now() - timedelta(days=6)).strftime("%Y-%m-%d")

        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError as e:
            return {"error": f"{tool_name}: 日期格式应为 YYYY-MM-DD: {e}"}

        if start_dt > end_dt:
            start_dt, end_dt = end_dt, start_dt

        span = (end_dt - start_dt).days + 1
        if span > _FORECAST_RANGE_MAX_DAYS:
            return {
                "error": (
                    f"{tool_name}: 范围过大（{span} 天），最多 "
                    f"{_FORECAST_RANGE_MAX_DAYS} 天，请缩小日期范围"
                )
            }

        if _is_mock():
            return {"error": f"{tool_name}: 未配置福加 API（FUCA_API_BASE_URL），无法获取真实数据"}

        items: List[Dict[str, Any]] = []
        cur = start_dt
        while cur <= end_dt:
            day_str = cur.strftime("%Y-%m-%d")
            path = (
                "/loadForecast/predict/realTime"
                if day_str == today
                else "/loadForecast/predict/changeRealTime"
            )
            # 逐日 try-except：单日获取失败（HTTP 异常或 error dict）只跳过该日，不拖垮整段导出
            try:
                rt = _api_post_pv(path, {
                    "startTime": day_str,
                    "endTime": day_str,
                    "type": "day",
                    "energyType": energy_type,
                })
                if not isinstance(rt, dict) or "error" in rt:
                    logger.warning(f"{tool_name}: 跳过 {day_str}（获取失败）")
                else:
                    sf = _build_pv_realtime(rt)
                    items.append(_flatten_forecast_day(day_str, sf))
            except Exception as e:
                logger.warning(f"{tool_name}: 跳过 {day_str}（异常: {e}）")
            cur += timedelta(days=1)

        return {
            "site_id": site_id,
            "start_date": start_dt.strftime("%Y-%m-%d"),
            "end_date": end_dt.strftime("%Y-%m-%d"),
            "energy_type": energy_type,
            "items": items,
            "total_days": len(items),
        }
    except Exception as e:
        logger.error(f"{tool_name} 失败: {e}")
        return {"error": f"{tool_name}: {e}"}


def fetch_pv_forecast_range(site_id: str, start_date: str = "", end_date: str = "") -> Dict[str, Any]:
    """获取多日光伏预测汇总（福加 loadForecast，energyType=pv，供导出表格）。

    用户问「导出最近N天光伏预测 / 光伏预测准确率对比」时，先用本工具取多日
    预测vs实际汇总，再调 export_data_table 生成 CSV。每日一行：预测/实际峰值与
    累计、点位、准确率、等级。日期 YYYY-MM-DD，「最近7天」= start_date 今天往前推
    6 天、end_date 今天；范围最多 31 天。

    Args:
        site_id: 站点 ID（如 FJJB000001）
        start_date: 起始日期 YYYY-MM-DD，默认今天往前推 6 天
        end_date: 结束日期 YYYY-MM-DD，默认今天

    Returns:
        dict: ``{site_id, start_date, end_date, energy_type="pv", items, total_days}``；
        失败返回 ``{"error": "fetch_pv_forecast_range: ..."}``
    """
    return _fetch_loadforecast_range(
        site_id, start_date, end_date, energy_type="pv", tool_name="fetch_pv_forecast_range"
    )


def fetch_load_forecast_range(site_id: str, start_date: str = "", end_date: str = "") -> Dict[str, Any]:
    """获取多日冷负荷预测汇总（福加 loadForecast，energyType=load，供导出表格）。

    与 :func:`fetch_pv_forecast_range` 同一 loadForecast 服务、同一行结构，仅
    energyType="load"。冷负荷行额外含 current_load_kw / predicted_load_kw /
    next_hour_forecast_kw（今日 realTime 才有，非今日为 null）。

    Args:
        site_id: 站点 ID（如 FJJB000001）
        start_date: 起始日期 YYYY-MM-DD，默认今天往前推 6 天
        end_date: 结束日期 YYYY-MM-DD，默认今天

    Returns:
        dict: ``{site_id, start_date, end_date, energy_type="load", items, total_days}``；
        失败返回 ``{"error": "fetch_load_forecast_range: ..."}``
    """
    return _fetch_loadforecast_range(
        site_id, start_date, end_date, energy_type="load", tool_name="fetch_load_forecast_range"
    )


def fetch_electricity_forecast(site_id: str, date: str = "", unit: str = "day") -> Dict[str, Any]:
    """获取电负荷预测数据（福加 loadForecast 接口，energyType=electricity，对应 /analysis/electricity-forecast）。

    与 :func:`fetch_load_forecast`（冷负荷）同一 loadForecast 服务、同一响应结构，仅
    energyType="electricity"。页面框架与光伏/冷负荷预测一致：预测vs实际曲线 + 天气预报 +
    昨日/上周对比 + 左上小面板（今日平均偏差/当前负荷/预测负荷/下小时预测）。

    命名区分（重要）：冷负荷 = fetch_load_forecast（energyType=load，/analysis/load-forecast）；
    电负荷 = fetch_electricity_forecast（energyType=electricity，/analysis/electricity-forecast）。
    两者工具名、energyType、跳转页面均不同，严禁混用。

    Args:
        site_id: 站点 ID（如 FJJB000001）
        date: 参考日期 YYYY-MM-DD，默认今天；unit=week 时传该周内任意一天，
            工具自动取周一~周日
        unit: 查询粒度 ``"day"``（默认）或 ``"week"``

    Returns:
        ForecastResult 的 dict 表示（energy_type="electricity"）；失败返回 ``{"error": "fetch_electricity_forecast: ..."}``
    """
    return _fetch_loadforecast(
        site_id, date, unit, energy_type="electricity", tool_name="fetch_electricity_forecast"
    )


def fetch_electricity_forecast_range(site_id: str, start_date: str = "", end_date: str = "") -> Dict[str, Any]:
    """获取多日电负荷预测汇总（福加 loadForecast，energyType=electricity，供导出表格）。

    与 :func:`fetch_load_forecast_range`（冷负荷）同一 loadForecast 服务、同一行结构，仅
    energyType="electricity"。每日一行：预测/实际峰值与累计、点位、准确率、等级、
    当前/预测/下小时负荷（今日行才有，非今日为 null）。

    命名区分（重要）：冷负荷多日导出 = fetch_load_forecast_range（energyType=load）；
    电负荷多日导出 = fetch_electricity_forecast_range（energyType=electricity）。严禁混用。

    Args:
        site_id: 站点 ID（如 FJJB000001）
        start_date: 起始日期 YYYY-MM-DD，默认今天往前推 6 天
        end_date: 结束日期 YYYY-MM-DD，默认今天

    Returns:
        dict: ``{site_id, start_date, end_date, energy_type="electricity", items, total_days}``；
        失败返回 ``{"error": "fetch_electricity_forecast_range: ..."}``
    """
    return _fetch_loadforecast_range(
        site_id, start_date, end_date, energy_type="electricity", tool_name="fetch_electricity_forecast_range"
    )
