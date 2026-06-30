"""test_pv_forecast — 光伏预测工具（fetch_pv_forecast）单元测试

测试范围：
  - 今日 day 模式：走 realTime，selected_forecast 带准确率/等级/下一小时预测
  - 非今日 day 模式：走 changeRealTime，accuracy="-"
  - week 模式：sel_start/end 取周一~周日，type=week，天气每日最高/最低
  - 昨日/上周对比恒以今日为基准（不受 date/unit 影响）
  - 请求体结构（startTime/endTime/type/energyType=pv）
  - 逐时点序列汇总（peak/total/valid_count/point_count，null 点处理）
  - ts 归一化（epoch 毫秒 → CST 字符串；日期字符串透传）
  - Mock 兜底 / 非法 unit / 非法日期
  - loadForecast 500（过期 Token）触发 refresh_token 刷新重试；持续 500 / 非 500 错误不刷新
  - 负荷预测（fetch_load_forecast, energyType=load）：共享核心、energyType 与光伏互不污染、路由映射、500 刷新
  - 路由映射：fetch_pv_forecast → /analysis/pv-forecast、fetch_load_forecast → /analysis/load-forecast（routes.yaml 动态构建）
  - 多日范围导出（fetch_pv/load_forecast_range）：默认 7 天、逐日 realTime/changeRealTime 选择、
    日期互换、31 天上限、Mock 兜底、单日失败/异常跳过、pv/load 互不污染、请求体结构、路由映射与自动跳转

纯计算 / Mock，不依赖 LLM / API Key。
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

# 添加项目根目录到 Python 路径
project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

from src.tools import java_backend  # noqa: E402
from src.tools.java_backend import (  # noqa: E402
    fetch_pv_forecast,
    fetch_load_forecast,
    fetch_pv_forecast_range,
    fetch_load_forecast_range,
    _pv_ts_to_str,
    _pv_series,
    _build_pv_realtime,
    _build_pv_history,
    _build_pv_weather,
    _flatten_forecast_day,
    _FORECAST_RANGE_MAX_DAYS,
)
from src.skills.ui_router_skill import UIRouterSkill, _TOOL_ROUTE_MAP  # noqa: E402


# ── 固定「今日」= 2026-06-30（周二），与 routes/页面行为对齐 ──────────

class _FakeDateTime(datetime):
    """冻结 now() 到 2026-06-30 10:11:33，其余（strptime/fromtimestamp）继承。"""

    _fixed = datetime(2026, 6, 30, 10, 11, 33)

    @classmethod
    def now(cls, tz=None):
        return cls._fixed


@pytest.fixture(autouse=True)
def _freeze_time(monkeypatch):
    """所有用例统一冻结 datetime，保证昨日=06-29、上周=06-22..06-28 可断言。"""
    monkeypatch.setattr(java_backend, "datetime", _FakeDateTime)


# ── fake loadForecast 响应 ───────────────────────────────────────────

def _fake_post(path, body):
    """按 path 与 body 分发假响应（结构对齐真实 loadForecast 接口）。"""
    if path.endswith("/predict/realTime"):
        return {
            "actualData": [
                {"ts": "1782748800000", "v": 0.0},       # 06-30 00:00
                {"ts": "1782781200000", "v": 147.0},     # 06-30 09:00（当前小时）
                {"ts": "2026-06-30 10:00:00", "v": None},  # 未来未出
            ],
            "forecastData": [
                {"ts": "1782748800000", "v": 0.0},
                {"ts": "1782781200000", "v": 162.08},
                {"ts": "1782784800000", "v": 259.97},   # 06-30 10:00 预测峰值
            ],
            "currentLoad": 5.0,
            "predictedLoad": 259.97,
            "accuracy": "18.5",
            "evaluationGrade": "一级",
            "nextHourFL": 276.91,
        }
    if path.endswith("/predict/changeRealTime"):
        return {
            "actualData": [
                {"ts": "1782748800000", "v": 0.0},
                {"ts": "1782781200000", "v": 147.0},
            ],
            "forecastData": [
                {"ts": "1782748800000", "v": 0.0},
                {"ts": "1782784800000", "v": 259.97},
            ],
            "currentLoad": 0.0,
            "predictedLoad": 259.97,
            "accuracy": "-",
            "evaluationGrade": None,
            "nextHourFL": None,
        }
    if path.endswith("/weather/v1/getWeather"):
        if body.get("type") == "week":
            return [
                {"skycon": "阴", "temperatureMin": 21.0, "temperatureMax": 25.0, "humidityAvg": 92.0},
                {"skycon": "晴", "temperatureMin": 22.0, "temperatureMax": 29.0, "humidityAvg": 64.0},
            ]
        return [
            {"skycon": "阴", "temperatureMin": 27.0, "temperatureMax": None, "humidityAvg": 91.0},
            {"skycon": "雨", "temperatureMin": 24.0, "temperatureMax": None, "humidityAvg": 100.0},
        ]
    if path.endswith("/predict/histPredict"):
        # 昨日（startTime=06-29）vs 上周（startTime=06-22）用不同准确率区分
        if body.get("startTime") == "2026-06-29":
            return {
                "actValue": [
                    {"ts": "1782662400000", "v": 0.0},     # 06-29 00:00
                    {"ts": "1782680400000", "v": 11.0},    # 06-29 05:00
                    {"ts": "1782716400000", "v": 185.0},   # 06-29 15:00 峰值
                ],
                "histPreValue": [
                    {"ts": "1782662400000", "v": 0.0},
                    {"ts": "1782716400000", "v": 157.04},
                ],
                "avaccuracy": "17.7",
            }
        # 上周 06-22..06-28
        return {
            "actValue": [
                {"ts": "1782057600000", "v": 5.0},      # 06-22 00:00
                {"ts": "1782360000000", "v": 341.0},    # 06-25 12:00 峰值
            ],
            "histPreValue": [
                {"ts": "1782057600000", "v": 0.0},
                {"ts": "1782360000000", "v": 362.43},
            ],
            "avaccuracy": "15.2",
        }
    return {}


def _setup_mock(monkeypatch):
    """绕过 Mock 兜底 + 注入假 _api_post。"""
    monkeypatch.setattr(java_backend, "_is_mock", lambda: False)
    monkeypatch.setattr(java_backend, "_api_post", _fake_post)


def _http_status_error(path: str, code: int) -> httpx.HTTPStatusError:
    """构造指定状态码的 httpx.HTTPStatusError，用于 mock loadForecast 的 HTTP 错误。

    Args:
        path: loadForecast 路径（仅用于构造 request URL）
        code: HTTP 状态码（如 500/502）

    Returns:
        httpx.HTTPStatusError 实例
    """
    req = httpx.Request("POST", f"https://aiot-fuca.com{path}")
    resp = httpx.Response(code, request=req)
    return httpx.HTTPStatusError(f"Server error '{code} '", request=req, response=resp)


# ── 今日 day 模式（realTime） ────────────────────────────────────────


class TestTodayDayMode:
    """date=今天、unit=day → 走 realTime，带准确率/等级。"""

    def test_today_uses_realtime_with_accuracy(self, monkeypatch):
        _setup_mock(monkeypatch)
        result = fetch_pv_forecast("FJJB000001")  # 默认 date=今天, unit=day

        assert "error" not in result
        assert result["today"] == "2026-06-30"
        assert result["date"] == "2026-06-30"
        assert result["unit"] == "day"

        sel = result["selected_forecast"]
        assert sel["accuracy"] == "18.5"
        assert sel["evaluation_grade"] == "一级"
        assert sel["next_hour_forecast_kw"] == 276.91
        assert sel["current_load_kw"] == 5.0
        assert sel["predicted_load_kw"] == 259.97

    def test_today_actual_series_summary(self, monkeypatch):
        """今日实际：peak=147，valid_count=2（排除未来 null），point_count=3。"""
        _setup_mock(monkeypatch)
        result = fetch_pv_forecast("FJJB000001")
        actual = result["selected_forecast"]["actual"]
        assert actual["peak_kw"] == 147.0
        assert actual["valid_count"] == 2
        assert actual["point_count"] == 3
        assert actual["first_ts"] == "2026-06-30 00:00:00"
        assert actual["last_ts"] == "2026-06-30 10:00:00"

    def test_today_forecast_series_summary(self, monkeypatch):
        """今日预测：peak=259.97，total=0+162.08+259.97。"""
        _setup_mock(monkeypatch)
        result = fetch_pv_forecast("FJJB000001")
        forecast = result["selected_forecast"]["forecast"]
        assert forecast["peak_kw"] == 259.97
        assert forecast["total_kwh"] == round(0.0 + 162.08 + 259.97, 2)
        assert forecast["valid_count"] == 3

    def test_today_weather_day_mode(self, monkeypatch):
        """日模式天气：tempMax 为 None，tempMin 为逐时温度。"""
        _setup_mock(monkeypatch)
        result = fetch_pv_forecast("FJJB000001")
        weather = result["weather"]
        assert len(weather) == 2
        assert weather[0]["skycon"] == "阴"
        assert weather[0]["temperature_min"] == 27.0
        assert weather[0]["temperature_max"] is None
        assert weather[0]["humidity_avg"] == 91.0

    def test_yesterday_and_last_week_today_relative(self, monkeypatch):
        """昨日=06-29、上周=06-22..06-28（恒以今日 06-30 为基准）。"""
        _setup_mock(monkeypatch)
        result = fetch_pv_forecast("FJJB000001")

        yest = result["yesterday"]
        assert yest["accuracy"] == "17.7"
        assert yest["actual"]["peak_kw"] == 185.0
        assert yest["actual"]["first_ts"] == "2026-06-29 00:00:00"

        lw = result["last_week"]
        assert lw["accuracy"] == "15.2"
        assert lw["actual"]["peak_kw"] == 341.0
        assert lw["actual"]["first_ts"] == "2026-06-22 00:00:00"


# ── 非今日 day 模式（changeRealTime） ───────────────────────────────


class TestOtherDayMode:
    """date=06-25、unit=day → 走 changeRealTime，accuracy="-"。"""

    def test_other_date_uses_change_realtime(self, monkeypatch):
        _setup_mock(monkeypatch)
        result = fetch_pv_forecast("FJJB000001", date="2026-06-25")

        assert "error" not in result
        assert result["today"] == "2026-06-30"
        assert result["date"] == "2026-06-25"
        sel = result["selected_forecast"]
        assert sel["accuracy"] == "-"
        assert sel["evaluation_grade"] is None
        assert sel["next_hour_forecast_kw"] is None

    def test_bottom_still_today_relative_when_date_differs(self, monkeypatch):
        """选了 06-25，但昨日/上周仍以今日 06-30 为基准（不是 06-25）。"""
        _setup_mock(monkeypatch)
        result = fetch_pv_forecast("FJJB000001", date="2026-06-25")
        # 昨日仍是 06-29（若以 06-25 为基准会是 06-24，avaccuracy 会不同）
        assert result["yesterday"]["accuracy"] == "17.7"
        assert result["last_week"]["accuracy"] == "15.2"


# ── week 模式 ───────────────────────────────────────────────────────


class TestWeekMode:
    """unit=week → sel 取周一~周日，type=week，天气每日最高/最低。"""

    def test_week_date_range(self, monkeypatch):
        _setup_mock(monkeypatch)
        # 06-25（周四）落在 06-22~06-28 那周
        result = fetch_pv_forecast("FJJB000001", date="2026-06-25", unit="week")

        assert result["unit"] == "week"
        assert result["date"] == "2026-06-22"  # 周一

    def test_week_weather_has_min_and_max(self, monkeypatch):
        _setup_mock(monkeypatch)
        result = fetch_pv_forecast("FJJB000001", date="2026-06-25", unit="week")
        weather = result["weather"]
        assert len(weather) == 2
        assert weather[0]["temperature_min"] == 21.0
        assert weather[0]["temperature_max"] == 25.0
        assert weather[0]["humidity_avg"] == 92.0

    def test_week_request_body(self, monkeypatch):
        """week 模式请求体：startTime=06-22, endTime=06-28, type=week。"""
        captured = []

        def spy(path, body):
            captured.append((path, body))
            return _fake_post(path, body)

        monkeypatch.setattr(java_backend, "_is_mock", lambda: False)
        monkeypatch.setattr(java_backend, "_api_post", spy)
        fetch_pv_forecast("FJJB000001", date="2026-06-25", unit="week")

        paths = {p for p, _ in captured}
        assert any(p.endswith("/predict/changeRealTime") for p in paths)
        crt_body = next(b for p, b in captured if p.endswith("/predict/changeRealTime"))
        assert crt_body == {
            "startTime": "2026-06-22", "endTime": "2026-06-28",
            "type": "week", "energyType": "pv",
        }
        wx_body = next(b for p, b in captured if p.endswith("/weather/v1/getWeather"))
        assert wx_body["type"] == "week"
        assert wx_body["startTime"] == "2026-06-22"
        assert wx_body["endTime"] == "2026-06-28"


# ── 请求体结构（今日 day 模式） ─────────────────────────────────────


class TestRequestBody:
    """验证各接口请求体结构与页面抓包一致。"""

    def test_today_day_request_bodies(self, monkeypatch):
        captured = []

        def spy(path, body):
            captured.append((path, body))
            return _fake_post(path, body)

        monkeypatch.setattr(java_backend, "_is_mock", lambda: False)
        monkeypatch.setattr(java_backend, "_api_post", spy)
        fetch_pv_forecast("FJJB000001")  # 今日 day

        paths = [p for p, _ in captured]
        # 今日走 realTime（不走 changeRealTime）
        assert any(p.endswith("/predict/realTime") for p in paths)
        assert not any(p.endswith("/predict/changeRealTime") for p in paths)

        rt = next(b for p, b in captured if p.endswith("/predict/realTime"))
        assert rt == {"startTime": "2026-06-30", "endTime": "2026-06-30",
                      "type": "day", "energyType": "pv"}

        wx = next(b for p, b in captured if p.endswith("/weather/v1/getWeather"))
        assert wx == {"startTime": "2026-06-30", "endTime": "2026-06-30",
                      "type": "day", "energyType": "pv"}

        # 昨日 histPredict
        yest = next(b for p, b in captured
                    if p.endswith("/predict/histPredict") and b["startTime"] == "2026-06-29")
        assert yest == {"startTime": "2026-06-29", "endTime": "2026-06-29",
                        "type": "day", "energyType": "pv"}

        # 上周 histPredict
        lw = next(b for p, b in captured
                  if p.endswith("/predict/histPredict") and b["startTime"] == "2026-06-22")
        assert lw == {"startTime": "2026-06-22", "endTime": "2026-06-28",
                      "type": "day", "energyType": "pv"}


# ── 序列汇总与 ts 归一化（纯函数） ──────────────────────────────────


class TestSeriesAndTs:
    """_pv_series / _pv_ts_to_str 纯函数测试。"""

    def test_ts_epoch_to_cst(self):
        assert _pv_ts_to_str("1782748800000") == "2026-06-30 00:00:00"
        assert _pv_ts_to_str("1782781200000") == "2026-06-30 09:00:00"
        assert _pv_ts_to_str("1782057600000") == "2026-06-22 00:00:00"

    def test_ts_date_string_passthrough(self):
        assert _pv_ts_to_str("2026-06-30 10:00:00") == "2026-06-30 10:00:00"

    def test_ts_none_and_invalid(self):
        assert _pv_ts_to_str(None) == ""
        assert _pv_ts_to_str("not-a-ts") == "not-a-ts"

    def test_series_null_points_excluded_from_peak_total(self):
        pts = [{"ts": "1", "v": 10.0}, {"ts": "2", "v": None}, {"ts": "3", "v": 5.0}]
        s = _pv_series(pts)
        assert s.peak_kw == 10.0
        assert s.total_kwh == 15.0
        assert s.valid_count == 2
        assert s.point_count == 3

    def test_series_all_null(self):
        s = _pv_series([{"ts": "1", "v": None}, {"ts": "2", "v": None}])
        assert s.peak_kw is None
        assert s.total_kwh is None
        assert s.valid_count == 0
        assert s.point_count == 2

    def test_series_empty_and_non_list(self):
        assert _pv_series([]).model_dump()["point_count"] == 0
        assert _pv_series(None).model_dump()["point_count"] == 0

    def test_build_realtime_handles_empty(self):
        """空响应不抛异常，字段安全降级。"""
        r = _build_pv_realtime({})
        assert r.actual.point_count == 0
        assert r.accuracy is None
        assert r.next_hour_forecast_kw is None

    def test_build_weather_non_list_returns_empty(self):
        assert _build_pv_weather({}) == []
        assert _build_pv_weather(None) == []

    def test_build_history_handles_empty(self):
        h = _build_pv_history({})
        assert h.actual.point_count == 0
        assert h.accuracy is None


# ── 异常与兜底 ──────────────────────────────────────────────────────


class TestErrorsAndFallback:
    """Mock 兜底 / 非法 unit / 非法日期。"""

    def test_mock_returns_error(self, monkeypatch):
        monkeypatch.setattr(java_backend, "_is_mock", lambda: True)
        result = fetch_pv_forecast("FJJB000001")
        assert "error" in result
        assert "FUCA_API_BASE_URL" in result["error"]

    def test_invalid_unit(self, monkeypatch):
        monkeypatch.setattr(java_backend, "_is_mock", lambda: False)
        result = fetch_pv_forecast("FJJB000001", unit="month")
        assert "error" in result
        assert "day 或 week" in result["error"]

    def test_invalid_date_format(self, monkeypatch):
        monkeypatch.setattr(java_backend, "_is_mock", lambda: False)
        result = fetch_pv_forecast("FJJB000001", date="2026/06/30")
        assert "error" in result
        assert "YYYY-MM-DD" in result["error"]

    def test_unit_case_insensitive(self, monkeypatch):
        """unit 大小写不敏感：'WEEK' 等价 'week'。"""
        _setup_mock(monkeypatch)
        result = fetch_pv_forecast("FJJB000001", date="2026-06-25", unit="WEEK")
        assert "error" not in result
        assert result["unit"] == "week"

    def test_api_exception_caught(self, monkeypatch):
        """底层 _api_post 抛异常 → 工具返回 error，不向 Agent 传播。"""
        monkeypatch.setattr(java_backend, "_is_mock", lambda: False)

        def boom(path, body):
            raise RuntimeError("连接超时")

        monkeypatch.setattr(java_backend, "_api_post", boom)
        result = fetch_pv_forecast("FJJB000001")
        assert "error" in result
        assert "fetch_pv_forecast" in result["error"]

    def test_500_triggers_refresh_then_succeeds(self, monkeypatch):
        """loadForecast 首次 500（过期 Token）→ 复用 refresh_token 刷新后重试成功。"""
        monkeypatch.setattr(java_backend, "_is_mock", lambda: False)
        refreshed = []
        monkeypatch.setattr(
            java_backend, "_refresh_token_if_possible", lambda: refreshed.append("ok") or "fresh-token"
        )
        calls = {"n": 0}

        def fake_post(path, body):
            calls["n"] += 1
            if calls["n"] == 1:
                raise _http_status_error(path, 500)
            return _fake_post(path, body)

        monkeypatch.setattr(java_backend, "_api_post", fake_post)
        result = fetch_pv_forecast("FJJB000001")
        assert "error" not in result
        assert refreshed == ["ok"]  # 500 触发了一次 refresh_token
        assert calls["n"] >= 2  # 首次 500 后重试

    def test_500_persistent_returns_error(self, monkeypatch):
        """loadForecast 持续 500（真实服务异常）→ 刷新后仍失败 → 工具返回 error，不崩溃。"""
        monkeypatch.setattr(java_backend, "_is_mock", lambda: False)
        monkeypatch.setattr(java_backend, "_refresh_token_if_possible", lambda: "fresh-token")

        def always_500(path, body):
            raise _http_status_error(path, 500)

        monkeypatch.setattr(java_backend, "_api_post", always_500)
        result = fetch_pv_forecast("FJJB000001")
        assert "error" in result
        assert "fetch_pv_forecast" in result["error"]

    def test_non_500_http_error_not_refreshed(self, monkeypatch):
        """502 等非 500 HTTP 错误不触发 Token 刷新，原样抛出 → 工具返回 error。"""
        monkeypatch.setattr(java_backend, "_is_mock", lambda: False)
        refreshed = []
        monkeypatch.setattr(
            java_backend, "_refresh_token_if_possible", lambda: refreshed.append("nope") or None
        )

        def boom_502(path, body):
            raise _http_status_error(path, 502)

        monkeypatch.setattr(java_backend, "_api_post", boom_502)
        result = fetch_pv_forecast("FJJB000001")
        assert "error" in result
        assert refreshed == []  # 502 不应触发刷新


# ── 路由映射与自动跳转 ──────────────────────────────────────────────


class TestRouteMapping:
    """fetch_pv_forecast → /analysis/pv-forecast（routes.yaml 动态构建）。"""

    def test_tool_route_map_has_pv_forecast(self):
        assert "/analysis/pv-forecast" in _TOOL_ROUTE_MAP.get("fetch_pv_forecast", [])

    def test_infer_navigation_auto_jumps(self):
        """LLM 只调 fetch_pv_forecast 未显式跳转时，UIRouterSkill 兜底跳 /analysis/pv-forecast。"""
        result = {"site_id": "FJJB000001", "today": "2026-06-30", "unit": "day"}
        tool_results = [("fetch_pv_forecast", result, {"site_id": "FJJB000001"})]
        actions = UIRouterSkill._infer_navigation(tool_results)
        assert len(actions) == 1
        assert actions[0].route == "/analysis/pv-forecast"
        assert actions[0].name == "光伏预测"

    def test_explicit_navigate_dedup_with_auto_map(self):
        """LLM 显式跳 /analysis/pv-forecast + fetch_pv_forecast 自动映射同路由 → 去重为 1 个。"""
        result = {"site_id": "FJJB000001", "today": "2026-06-30"}
        nav_result = {"route": "/analysis/pv-forecast", "name": "光伏预测"}
        tool_results = [
            ("fetch_pv_forecast", result, {"site_id": "FJJB000001"}),
            ("navigate_to_page", nav_result, {"route": "/analysis/pv-forecast"}),
        ]
        actions = UIRouterSkill._infer_navigation(tool_results)
        # 同路由去重：显式跳转 + 自动映射合并为 1 个
        assert len(actions) == 1
        assert actions[0].route == "/analysis/pv-forecast"

    def test_explicit_navigate_different_route_kept_with_auto_map(self):
        """LLM 显式跳转 A 路由 + fetch_pv_forecast 自动映射 B 路由 → 两个跳转都保留。"""
        result = {"site_id": "FJJB000001", "today": "2026-06-30"}
        nav_result = {"route": "/coordination/energy", "name": "光储实时能量"}
        tool_results = [
            ("fetch_pv_forecast", result, {"site_id": "FJJB000001"}),
            ("navigate_to_page", nav_result, {"route": "/coordination/energy"}),
        ]
        actions = UIRouterSkill._infer_navigation(tool_results)
        routes = {a.route for a in actions}
        assert routes == {"/coordination/energy", "/analysis/pv-forecast"}


# ── 负荷预测（冷负荷，energyType=load） ─────────────────────────────


class TestLoadForecast:
    """fetch_load_forecast 与 fetch_pv_forecast 共享 _fetch_loadforecast 核心，仅 energyType=load。"""

    def test_load_returns_result_with_energy_type(self, monkeypatch):
        _setup_mock(monkeypatch)
        result = fetch_load_forecast("FJJB000001")
        assert "error" not in result
        assert result["energy_type"] == "load"
        assert result["unit"] == "day"

    def test_load_uses_load_energy_type_in_all_bodies(self, monkeypatch):
        """负荷预测所有请求体 energyType=load，绝不混入 pv。"""
        captured = []

        def spy(path, body):
            captured.append((path, body))
            return _fake_post(path, body)

        monkeypatch.setattr(java_backend, "_is_mock", lambda: False)
        monkeypatch.setattr(java_backend, "_api_post", spy)
        fetch_load_forecast("FJJB000001")  # 今日 day

        assert captured, "应至少发出一个请求"
        for _path, body in captured:
            assert body["energyType"] == "load", f"负荷预测请求体 energyType 应为 load：{body}"

    def test_pv_and_load_use_different_energy_types(self, monkeypatch):
        """同一进程内 pv→energyType=pv、load→energyType=load 互不污染。"""
        pv_bodies, load_bodies = [], []

        def make_spy(bucket):
            def spy(path, body):
                bucket.append((path, body))
                return _fake_post(path, body)
            return spy

        monkeypatch.setattr(java_backend, "_is_mock", lambda: False)

        monkeypatch.setattr(java_backend, "_api_post", make_spy(pv_bodies))
        fetch_pv_forecast("FJJB000001")
        monkeypatch.setattr(java_backend, "_api_post", make_spy(load_bodies))
        fetch_load_forecast("FJJB000001")

        assert all(b["energyType"] == "pv" for _, b in pv_bodies)
        assert all(b["energyType"] == "load" for _, b in load_bodies)

    def test_load_today_uses_realtime(self, monkeypatch):
        """今日 day 模式走 realTime（与光伏一致），不走 changeRealTime。"""
        captured = []

        def spy(path, body):
            captured.append(path)
            return _fake_post(path, body)

        monkeypatch.setattr(java_backend, "_is_mock", lambda: False)
        monkeypatch.setattr(java_backend, "_api_post", spy)
        fetch_load_forecast("FJJB000001")

        assert any(p.endswith("/predict/realTime") for p in captured)
        assert not any(p.endswith("/predict/changeRealTime") for p in captured)

    def test_load_route_map_has_load_forecast(self):
        assert "/analysis/load-forecast" in _TOOL_ROUTE_MAP.get("fetch_load_forecast", [])

    def test_load_infer_navigation_auto_jumps(self):
        """LLM 只调 fetch_load_forecast 未显式跳转时，兜底跳 /analysis/load-forecast。"""
        result = {"site_id": "FJJB000001", "today": "2026-06-30", "energy_type": "load"}
        tool_results = [("fetch_load_forecast", result, {"site_id": "FJJB000001"})]
        actions = UIRouterSkill._infer_navigation(tool_results)
        assert len(actions) == 1
        assert actions[0].route == "/analysis/load-forecast"
        assert actions[0].name == "负荷预测"

    def test_load_500_triggers_refresh_then_succeeds(self, monkeypatch):
        """负荷预测同样走 _api_post_pv：500（过期 Token）触发 refresh_token 重试成功。"""
        monkeypatch.setattr(java_backend, "_is_mock", lambda: False)
        refreshed = []
        monkeypatch.setattr(
            java_backend, "_refresh_token_if_possible", lambda: refreshed.append("ok") or "fresh-token"
        )
        calls = {"n": 0}

        def fake_post(path, body):
            calls["n"] += 1
            if calls["n"] == 1:
                raise _http_status_error(path, 500)
            return _fake_post(path, body)

        monkeypatch.setattr(java_backend, "_api_post", fake_post)
        result = fetch_load_forecast("FJJB000001")
        assert "error" not in result
        assert refreshed == ["ok"]
        assert calls["n"] >= 2

    def test_load_error_prefix_is_load(self, monkeypatch):
        """负荷预测异常前缀为 fetch_load_forecast，不串用光伏。"""
        monkeypatch.setattr(java_backend, "_is_mock", lambda: True)
        result = fetch_load_forecast("FJJB000001")
        assert "error" in result
        assert "fetch_load_forecast" in result["error"]
        assert "fetch_pv_forecast" not in result["error"]


# ── 多日范围导出（fetch_pv/load_forecast_range） ─────────────────────


class TestForecastRange:
    """fetch_pv_forecast_range / fetch_load_forecast_range 多日汇总（供 export_data_table）。

    每日只调一个接口（今日 realTime、其余 changeRealTime），不复用 weather/histPredict；
    单日失败（error dict 或异常）只跳过该日，不拖垮整段导出。
    """

    # ── 正常输入：默认 7 天 + 逐日接口选择 ──────────────────────────

    def test_default_range_seven_days(self, monkeypatch):
        """默认 start=今天-6、end=今天 → 06-24..06-30 共 7 天。"""
        _setup_mock(monkeypatch)
        result = fetch_pv_forecast_range("FJJB000001")

        assert "error" not in result
        assert result["start_date"] == "2026-06-24"
        assert result["end_date"] == "2026-06-30"
        assert result["energy_type"] == "pv"
        assert result["total_days"] == 7
        assert len(result["items"]) == 7
        assert result["items"][0]["date"] == "2026-06-24"
        assert result["items"][-1]["date"] == "2026-06-30"

    def test_today_row_uses_realtime(self, monkeypatch):
        """今日（06-30）走 realTime：forecast_total=422.05、point_count=3、accuracy=18.5、
        current_load=5.0、next_hour_forecast=276.91、evaluation_grade=一级。"""
        _setup_mock(monkeypatch)
        result = fetch_pv_forecast_range("FJJB000001")
        today_row = next(r for r in result["items"] if r["date"] == "2026-06-30")

        assert today_row["forecast_peak_kw"] == 259.97
        assert today_row["forecast_total_kwh"] == round(0.0 + 162.08 + 259.97, 2)
        assert today_row["forecast_point_count"] == 3
        assert today_row["actual_peak_kw"] == 147.0
        assert today_row["actual_point_count"] == 3  # realTime 含未来 null 点
        assert today_row["accuracy"] == "18.5"
        assert today_row["evaluation_grade"] == "一级"
        assert today_row["current_load_kw"] == 5.0
        assert today_row["predicted_load_kw"] == 259.97
        assert today_row["next_hour_forecast_kw"] == 276.91

    def test_non_today_rows_use_change_realtime(self, monkeypatch):
        """非今日走 changeRealTime：forecast_total=259.97、point_count=2、accuracy=-、
        current_load=0.0、next_hour_forecast=None。"""
        _setup_mock(monkeypatch)
        result = fetch_pv_forecast_range("FJJB000001")
        non_today = [r for r in result["items"] if r["date"] != "2026-06-30"]

        assert len(non_today) == 6
        for row in non_today:
            assert row["forecast_peak_kw"] == 259.97
            assert row["forecast_total_kwh"] == round(0.0 + 259.97, 2)
            assert row["forecast_point_count"] == 2  # changeRealTime 无未来 null 点
            assert row["actual_point_count"] == 2
            assert row["accuracy"] == "-"
            assert row["evaluation_grade"] is None
            assert row["current_load_kw"] == 0.0
            assert row["next_hour_forecast_kw"] is None

    def test_custom_range_three_days(self, monkeypatch):
        """显式 06-28..06-30 → 3 行，末行今日走 realTime。"""
        _setup_mock(monkeypatch)
        result = fetch_pv_forecast_range("FJJB000001", "2026-06-28", "2026-06-30")

        assert "error" not in result
        assert result["total_days"] == 3
        assert [r["date"] for r in result["items"]] == ["2026-06-28", "2026-06-29", "2026-06-30"]
        # 06-28/06-29 走 changeRealTime（accuracy=-），06-30 走 realTime（accuracy=18.5）
        by_date = {r["date"]: r for r in result["items"]}
        assert by_date["2026-06-28"]["accuracy"] == "-"
        assert by_date["2026-06-29"]["accuracy"] == "-"
        assert by_date["2026-06-30"]["accuracy"] == "18.5"

    # ── 边界：日期互换 / 31 天上限 / 非法日期 ──────────────────────

    def test_reversed_dates_auto_swap(self, monkeypatch):
        """start>end 自动互换：06-30..06-28 → 06-28..06-30，3 行。"""
        _setup_mock(monkeypatch)
        result = fetch_pv_forecast_range("FJJB000001", "2026-06-30", "2026-06-28")

        assert "error" not in result
        assert result["start_date"] == "2026-06-28"
        assert result["end_date"] == "2026-06-30"
        assert result["total_days"] == 3

    def test_range_too_large_error(self, monkeypatch):
        """超过 31 天上限 → error，且不发起任何请求。"""
        captured = []

        def spy(path, body):
            captured.append(path)
            return _fake_post(path, body)

        monkeypatch.setattr(java_backend, "_is_mock", lambda: False)
        monkeypatch.setattr(java_backend, "_api_post", spy)
        # 05-01..06-30 = 61 天
        result = fetch_pv_forecast_range("FJJB000001", "2026-05-01", "2026-06-30")

        assert "error" in result
        assert "范围过大" in result["error"]
        assert str(_FORECAST_RANGE_MAX_DAYS) in result["error"]
        assert captured == []  # 上限校验在请求前，不应发任何请求

    def test_invalid_date_format(self, monkeypatch):
        monkeypatch.setattr(java_backend, "_is_mock", lambda: False)
        result = fetch_pv_forecast_range("FJJB000001", "2026/06/30", "2026-06-30")
        assert "error" in result
        assert "YYYY-MM-DD" in result["error"]

    # ── 效率：每日只调 realTime/changeRealTime，不调 weather/histPredict ──

    def test_only_realtime_or_changerealtime_called(self, monkeypatch):
        """多日导出每日 1 个请求，且只走 realTime/changeRealTime（无 weather/histPredict）。"""
        captured = []

        def spy(path, body):
            captured.append(path)
            return _fake_post(path, body)

        monkeypatch.setattr(java_backend, "_is_mock", lambda: False)
        monkeypatch.setattr(java_backend, "_api_post", spy)
        fetch_pv_forecast_range("FJJB000001", "2026-06-28", "2026-06-30")

        assert len(captured) == 3  # 3 天 × 每天 1 个请求
        for p in captured:
            assert p.endswith("/predict/realTime") or p.endswith("/predict/changeRealTime")
            assert not p.endswith("/weather/v1/getWeather")
            assert not p.endswith("/predict/histPredict")
        # 仅今日走 realTime
        assert sum(1 for p in captured if p.endswith("/predict/realTime")) == 1
        assert sum(1 for p in captured if p.endswith("/predict/changeRealTime")) == 2

    def test_per_day_request_body(self, monkeypatch):
        """每日请求体：startTime=endTime=当日、type=day、energyType=pv。"""
        captured = []

        def spy(path, body):
            captured.append((path, body))
            return _fake_post(path, body)

        monkeypatch.setattr(java_backend, "_is_mock", lambda: False)
        monkeypatch.setattr(java_backend, "_api_post", spy)
        fetch_pv_forecast_range("FJJB000001", "2026-06-28", "2026-06-30")

        assert len(captured) == 3
        for _path, body in captured:
            assert body["startTime"] == body["endTime"]
            assert body["type"] == "day"
            assert body["energyType"] == "pv"
        dates = {b["startTime"] for _, b in captured}
        assert dates == {"2026-06-28", "2026-06-29", "2026-06-30"}

    # ── 单日失败：error dict / 异常 都只跳过该日 ────────────────────

    def test_per_day_error_dict_skipped(self, monkeypatch):
        """某日 _api_post 返回 error dict → 该日跳过，其余正常返回。"""
        def spy(path, body):
            if body.get("startTime") == "2026-06-29":
                return {"error": "simulated 500"}
            return _fake_post(path, body)

        monkeypatch.setattr(java_backend, "_is_mock", lambda: False)
        monkeypatch.setattr(java_backend, "_api_post", spy)
        result = fetch_pv_forecast_range("FJJB000001", "2026-06-28", "2026-06-30")

        assert "error" not in result
        assert result["total_days"] == 2
        assert [r["date"] for r in result["items"]] == ["2026-06-28", "2026-06-30"]

    def test_per_day_exception_skipped(self, monkeypatch):
        """某日 _api_post 抛异常（经 _api_post_pv 传播）→ 逐日 try 兜住，只跳过该日。"""
        def spy(path, body):
            if body.get("startTime") == "2026-06-29":
                raise RuntimeError("连接超时")
            return _fake_post(path, body)

        monkeypatch.setattr(java_backend, "_is_mock", lambda: False)
        monkeypatch.setattr(java_backend, "_api_post", spy)
        result = fetch_pv_forecast_range("FJJB000001", "2026-06-28", "2026-06-30")

        assert "error" not in result
        assert result["total_days"] == 2
        assert [r["date"] for r in result["items"]] == ["2026-06-28", "2026-06-30"]

    def test_all_days_fail_returns_empty_items(self, monkeypatch):
        """所有日均失败 → 不报错，items 为空、total_days=0（导出层自行提示无数据）。"""
        def spy(path, body):
            return {"error": "全挂"}

        monkeypatch.setattr(java_backend, "_is_mock", lambda: False)
        monkeypatch.setattr(java_backend, "_api_post", spy)
        result = fetch_pv_forecast_range("FJJB000001", "2026-06-28", "2026-06-30")

        assert "error" not in result
        assert result["items"] == []
        assert result["total_days"] == 0

    # ── Mock 兜底 ──────────────────────────────────────────────────

    def test_mock_returns_error(self, monkeypatch):
        monkeypatch.setattr(java_backend, "_is_mock", lambda: True)
        result = fetch_pv_forecast_range("FJJB000001")
        assert "error" in result
        assert "FUCA_API_BASE_URL" in result["error"]

    # ── 负荷预测范围：energyType=load，与光伏互不污染 ──────────────

    def test_load_range_energy_type_load(self, monkeypatch):
        _setup_mock(monkeypatch)
        result = fetch_load_forecast_range("FJJB000001", "2026-06-28", "2026-06-30")
        assert "error" not in result
        assert result["energy_type"] == "load"
        assert result["total_days"] == 3

    def test_load_range_bodies_use_load_energy_type(self, monkeypatch):
        captured = []

        def spy(path, body):
            captured.append(body)
            return _fake_post(path, body)

        monkeypatch.setattr(java_backend, "_is_mock", lambda: False)
        monkeypatch.setattr(java_backend, "_api_post", spy)
        fetch_load_forecast_range("FJJB000001", "2026-06-28", "2026-06-30")

        assert captured, "应至少发出一个请求"
        for body in captured:
            assert body["energyType"] == "load", f"负荷范围请求体 energyType 应为 load：{body}"

    def test_pv_and_load_range_no_cross_contamination(self, monkeypatch):
        """同一进程内 pv 范围→energyType=pv、load 范围→energyType=load 互不污染。"""
        pv_bodies, load_bodies = [], []

        def make_spy(bucket):
            def spy(path, body):
                bucket.append(body)
                return _fake_post(path, body)
            return spy

        monkeypatch.setattr(java_backend, "_is_mock", lambda: False)
        monkeypatch.setattr(java_backend, "_api_post", make_spy(pv_bodies))
        fetch_pv_forecast_range("FJJB000001", "2026-06-28", "2026-06-30")
        monkeypatch.setattr(java_backend, "_api_post", make_spy(load_bodies))
        fetch_load_forecast_range("FJJB000001", "2026-06-28", "2026-06-30")

        assert all(b["energyType"] == "pv" for b in pv_bodies)
        assert all(b["energyType"] == "load" for b in load_bodies)

    def test_load_range_error_prefix_is_load(self, monkeypatch):
        """负荷范围异常前缀为 fetch_load_forecast_range，不串用光伏。"""
        monkeypatch.setattr(java_backend, "_is_mock", lambda: True)
        result = fetch_load_forecast_range("FJJB000001")
        assert "error" in result
        assert "fetch_load_forecast_range" in result["error"]
        assert "fetch_pv_forecast_range" not in result["error"]

    # ── 路由映射与自动跳转 ─────────────────────────────────────────

    def test_pv_range_route_map(self):
        assert "/analysis/pv-forecast" in _TOOL_ROUTE_MAP.get("fetch_pv_forecast_range", [])

    def test_load_range_route_map(self):
        assert "/analysis/load-forecast" in _TOOL_ROUTE_MAP.get("fetch_load_forecast_range", [])

    def test_pv_range_auto_jumps(self):
        """LLM 只调 fetch_pv_forecast_range 未显式跳转时，兜底跳 /analysis/pv-forecast。"""
        result = {"site_id": "FJJB000001", "energy_type": "pv", "items": [], "total_days": 0}
        tool_results = [("fetch_pv_forecast_range", result, {"site_id": "FJJB000001"})]
        actions = UIRouterSkill._infer_navigation(tool_results)
        assert len(actions) == 1
        assert actions[0].route == "/analysis/pv-forecast"
        assert actions[0].name == "光伏预测"

    def test_load_range_auto_jumps(self):
        """LLM 只调 fetch_load_forecast_range 未显式跳转时，兜底跳 /analysis/load-forecast。"""
        result = {"site_id": "FJJB000001", "energy_type": "load", "items": [], "total_days": 0}
        tool_results = [("fetch_load_forecast_range", result, {"site_id": "FJJB000001"})]
        actions = UIRouterSkill._infer_navigation(tool_results)
        assert len(actions) == 1
        assert actions[0].route == "/analysis/load-forecast"
        assert actions[0].name == "负荷预测"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
