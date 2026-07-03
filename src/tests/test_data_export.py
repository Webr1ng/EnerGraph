"""test_data_export — Phase 6 数据导出（统一 CSV 模板）单元测试

测试范围：
  - export_data_table：正常导出 / 自动选图 / 空 rows / columns 自动推导 / 自定义文件名
  - fetch_energy_range：日期循环 + 跳过失败日 + Mock 兜底 + 非法日期
  - fetch_alarm_history：records 解析 + Mock 兜底 + 空记录
  - UIRouterSkill._infer_data_cards：提取 DataCard / 跳过 error / 跳过非 DataCard
  - GET /export/{task_id}：下载 200 / 文件不存在 404 / 非法 task_id 400 / 路径穿越拦截
  - SSE event: data_card：mock graph 后 /stream 推送 data_card 事件

纯计算 / Mock，不依赖 LLM / API Key。
"""
import json
import sys
from pathlib import Path

import pytest

# 添加项目根目录到 Python 路径
project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

from src.tools.export_data import export_data_table, _EXPORT_DIR  # noqa: E402
from src.tools import java_backend  # noqa: E402
from src.tools.java_backend import fetch_energy_range, fetch_alarm_history  # noqa: E402
from src.skills.ui_router_skill import UIRouterSkill  # noqa: E402
from src.schemas.data_card import ColumnDef  # noqa: E402
from src.utils.chart_recommender import recommend_chart  # noqa: E402


# ── export_data_table ────────────────────────────────────────────────


class TestExportDataTable:
    """通用导出工具 export_data_table 测试。"""

    def test_normal_export(self):
        """正常导出：生成 CSV + DataCard（含 download.url/task_id）。"""
        cols = [
            {"key": "date", "label": "日期", "unit": ""},
            {"key": "total_consumption_kwh", "label": "总用电量", "unit": "kWh"},
        ]
        rows = [
            {"date": "2026-06-20", "total_consumption_kwh": 1234.5},
            {"date": "2026-06-21", "total_consumption_kwh": 1450.0},
        ]
        card = export_data_table("FJJB000001 近7天能耗汇总", cols, rows)

        assert "error" not in card
        assert card["card_type"] == "table_chart"
        assert card["chart"]["type"] == "line"
        assert card["title"] == "FJJB000001 近7天能耗汇总"
        assert card["table"]["columns"][0]["label"] == "日期"
        assert len(card["table"]["rows"]) == 2

        download = card["download"]
        assert download["format"] == "csv"
        assert download["task_id"]
        assert download["url"] == f"/export/{download['task_id']}"
        assert download["filename"].endswith(".csv")

        # CSV 文件真实落盘，表头含中文 + 单位
        csv_path = _EXPORT_DIR / f"{download['task_id']}.csv"
        assert csv_path.is_file()
        content = csv_path.read_text(encoding="utf-8-sig")
        assert "日期" in content
        assert "总用电量 (kWh)" in content
        assert "1234.5" in content
        assert "2026-06-21" in content

    def test_empty_rows(self):
        """空 rows：仍生成 CSV（仅表头），DataCard.rows 为空。"""
        cols = [{"key": "date", "label": "日期", "unit": ""}]
        card = export_data_table("空表", cols, [])

        assert "error" not in card
        assert card["table"]["rows"] == []
        csv_path = _EXPORT_DIR / f"{card['download']['task_id']}.csv"
        # 仅表头一行
        lines = csv_path.read_text(encoding="utf-8-sig").strip().splitlines()
        assert len(lines) == 1
        assert lines[0] == "日期"

    def test_auto_derive_columns(self):
        """columns 为空时从首行 keys 推导（label = key）。"""
        rows = [{"date": "2026-06-20", "total": 100}, {"date": "2026-06-21", "total": 200}]
        card = export_data_table("自动推导", [], rows)

        assert "error" not in card
        keys = [c["key"] for c in card["table"]["columns"]]
        assert keys == ["date", "total"]
        # 推导时 label 回退为 key
        assert card["table"]["columns"][0]["label"] == "date"
        # CSV 用 label 作表头
        csv_path = _EXPORT_DIR / f"{card['download']['task_id']}.csv"
        first_line = csv_path.read_text(encoding="utf-8-sig").splitlines()[0]
        assert "date" in first_line and "total" in first_line

    def test_custom_filename(self):
        """filename 指定时 download.filename 使用它。"""
        card = export_data_table(
            "带文件名", [{"key": "a", "label": "A", "unit": ""}], [{"a": 1}], filename="my_export.csv"
        )
        assert card["download"]["filename"] == "my_export.csv"


class TestRecommendChart:
    """自动选图器只基于输入 rows 生成渲染规范。"""

    def test_comparison_uses_bar(self):
        """分类字段与数值字段推荐柱状图。"""
        columns = [ColumnDef(key="device", label="设备"), ColumnDef(key="energy", label="用电量", unit="kWh")]
        chart = recommend_chart("设备用电比较", columns, [{"device": "A", "energy": 10}, {"device": "B", "energy": 20}])
        assert chart is not None
        assert chart.type == "bar"

    def test_composition_uses_single_series_pie(self):
        """明确构成语义时仅使用首个数值序列绘制饼图。"""
        columns = [
            ColumnDef(key="source", label="来源"),
            ColumnDef(key="energy", label="电量"),
            ColumnDef(key="cost", label="成本"),
        ]
        chart = recommend_chart(
            "能源构成占比",
            columns,
            [{"source": "光伏", "energy": 30, "cost": 2}, {"source": "电网", "energy": 70, "cost": 8}],
        )
        assert chart is not None
        assert chart.type == "pie"
        assert [item.key for item in chart.series] == ["energy"]

    def test_none_hint_disables_chart(self):
        """none 提示始终退化为表格与 CSV。"""
        columns = [ColumnDef(key="date", label="日期"), ColumnDef(key="energy", label="电量")]
        assert recommend_chart("趋势", columns, [{"date": "2026-07-01", "energy": 1}, {"date": "2026-07-02", "energy": 2}], "none") is None

    def test_invalid_hint_returns_tool_error(self):
        """非法提示由工具统一转换为标准错误结构。"""
        card = export_data_table(
            "非法提示",
            [{"key": "date", "label": "日期"}, {"key": "energy", "label": "电量"}],
            [{"date": "2026-07-01", "energy": 1}, {"date": "2026-07-02", "energy": 2}],
            chart_hint="scatter",
        )
        assert card["error"].startswith("export_data_table:")


# ── fetch_energy_range ───────────────────────────────────────────────


class TestFetchEnergyRange:
    """多日能耗汇总 fetch_energy_range 测试。"""

    def test_date_loop(self, monkeypatch):
        """逐日循环 fetch_energy_summary，聚合 items + total_days。"""
        # 绕过 Mock 兜底
        monkeypatch.setattr(java_backend, "_is_mock", lambda: False)

        def fake_summary(site_id, date=""):
            return {"site_id": site_id, "date": date, "total_consumption_kwh": 1000.0}

        monkeypatch.setattr(java_backend, "fetch_energy_summary", fake_summary)

        result = fetch_energy_range("FJJB000001", "2026-06-20", "2026-06-22")
        assert "error" not in result
        assert result["site_id"] == "FJJB000001"
        assert result["start_date"] == "2026-06-20"
        assert result["end_date"] == "2026-06-22"
        assert result["total_days"] == 3
        assert [item["date"] for item in result["items"]] == [
            "2026-06-20", "2026-06-21", "2026-06-22"
        ]

    def test_skips_error_days(self, monkeypatch):
        """单日获取失败的日期跳过，不计入 items。"""
        monkeypatch.setattr(java_backend, "_is_mock", lambda: False)

        def fake_summary(site_id, date=""):
            if date == "2026-06-21":
                return {"error": "fetch_energy_summary: 模拟失败"}
            return {"site_id": site_id, "date": date, "total_consumption_kwh": 500.0}

        monkeypatch.setattr(java_backend, "fetch_energy_summary", fake_summary)

        result = fetch_energy_range("FJJB000001", "2026-06-20", "2026-06-22")
        assert result["total_days"] == 2
        assert [item["date"] for item in result["items"]] == ["2026-06-20", "2026-06-22"]

    def test_swaps_reversed_range(self, monkeypatch):
        """start > end 时自动交换。"""
        monkeypatch.setattr(java_backend, "_is_mock", lambda: False)
        monkeypatch.setattr(
            java_backend, "fetch_energy_summary", lambda site_id, date="": {"date": date}
        )
        result = fetch_energy_range("FJJB000001", "2026-06-22", "2026-06-20")
        assert result["start_date"] == "2026-06-20"
        assert result["end_date"] == "2026-06-22"
        assert result["total_days"] == 3

    def test_mock_returns_error(self, monkeypatch):
        """未配置 API（_is_mock=True）→ 返回 error，不抛异常、不返假数据。"""
        monkeypatch.setattr(java_backend, "_is_mock", lambda: True)
        result = fetch_energy_range("FJJB000001", "2026-06-20", "2026-06-22")
        assert "error" in result
        assert "FUCA_API_BASE_URL" in result["error"]

    def test_invalid_date_format(self):
        """非法日期格式 → 返回 error。"""
        result = fetch_energy_range("FJJB000001", "2026/06/20", "2026-06-22")
        assert "error" in result
        assert "YYYY-MM-DD" in result["error"]


# ── fetch_alarm_history ──────────────────────────────────────────────


class TestFetchAlarmHistory:
    """历史报警明细 fetch_alarm_history 测试。"""

    def test_parses_records(self, monkeypatch):
        """listHisAlarms records 解析为 AlarmItem dict，total 正确。"""
        monkeypatch.setattr(java_backend, "_is_mock", lambda: False)

        fake_records = {
            "records": [
                {
                    "alarmInfoId": "A1",
                    "alarmLevel": {"value": 4, "code": 4, "mes": "严重"},
                    "deviceName": "1#磁悬浮主机",
                    "alarmContent": "冷冻水出水温度过高",
                    "firstTime": "2026-06-21 10:00:00",
                    "recoverTime": "2026-06-21 11:00:00",
                },
                {
                    "alarmInfoId": "A2",
                    "alarmLevel": "warning",
                    "deviceName": "2#冷却水泵",
                    "alarmContent": "电流偏移",
                    "firstTime": "2026-06-22 09:00:00",
                    "recoverTime": None,
                },
            ]
        }
        monkeypatch.setattr(java_backend, "_api_post", lambda path, json_body: fake_records)

        result = fetch_alarm_history("FJJB000001", "2026-06-20", "2026-06-22")
        assert "error" not in result
        assert result["total"] == 2
        assert result["items"][0]["alarm_id"] == "A1"
        assert result["items"][0]["level"] == "严重"
        assert result["items"][0]["acknowledged"] is True
        assert result["items"][1]["level"] == "warning"
        assert result["items"][1]["acknowledged"] is False

        # 请求体含日期范围时间戳
        # （通过 fake 捕获最后一次调用参数验证）
        captured = {}

        def spy(path, json_body):
            captured["body"] = json_body
            return fake_records

        monkeypatch.setattr(java_backend, "_api_post", spy)
        fetch_alarm_history("FJJB000001", "2026-06-20", "2026-06-22")
        assert captured["body"]["startTime"] == "2026-06-20 00:00:00"
        assert captured["body"]["endTime"] == "2026-06-22 23:59:59"
        assert captured["body"]["pageNum"] == 1

    def test_empty_records(self, monkeypatch):
        """无报警记录 → items 为空，total 0。"""
        monkeypatch.setattr(java_backend, "_is_mock", lambda: False)
        monkeypatch.setattr(java_backend, "_api_post", lambda path, json_body: {"records": []})
        result = fetch_alarm_history("FJJB000001", "2026-06-20", "2026-06-22")
        assert result["total"] == 0
        assert result["items"] == []

    def test_mock_returns_error(self, monkeypatch):
        """未配置 API（_is_mock=True）→ 返回 error。"""
        monkeypatch.setattr(java_backend, "_is_mock", lambda: True)
        result = fetch_alarm_history("FJJB000001", "2026-06-20", "2026-06-22")
        assert "error" in result
        assert "FUCA_API_BASE_URL" in result["error"]


# ── UIRouterSkill._infer_data_cards ──────────────────────────────────


class TestInferDataCards:
    """UIRouterSkill DataCard 提取测试。"""

    @staticmethod
    def _card_result(title="测试卡片"):
        """生成一个合法的 export_data_table 结果。"""
        return export_data_table(
            title,
            [{"key": "date", "label": "日期", "unit": ""}],
            [{"date": "2026-06-20"}],
        )

    def test_extracts_datacard(self):
        """export_data_table 成功结果被提取为 DataCard。"""
        card = self._card_result()
        tool_results = [("export_data_table", card, {"title": "测试卡片"})]
        cards = UIRouterSkill._infer_data_cards(tool_results)
        assert len(cards) == 1
        assert cards[0]["download"]["task_id"] == card["download"]["task_id"]

    def test_skips_error_results(self):
        """export_data_table 返回 error 时跳过。"""
        tool_results = [("export_data_table", {"error": "export_data_table: 失败"}, {})]
        assert UIRouterSkill._infer_data_cards(tool_results) == []

    def test_skips_non_datacard_dicts(self):
        """非 export_data_table 工具结果（如 fetch_energy_range）不被误提取。"""
        energy_result = {
            "site_id": "FJJB000001",
            "items": [{"date": "2026-06-20"}],
            "total_days": 1,
        }
        tool_results = [("fetch_energy_range", energy_result, {})]
        assert UIRouterSkill._infer_data_cards(tool_results) == []

    def test_execute_returns_pending_data_cards(self):
        """execute 同时返回 pending_actions（跳转）+ pending_data_cards（导出）。"""
        card = self._card_result()
        # fetch_energy_range 触发自动跳转 + export_data_table 触发 DataCard
        tool_results = [
            ("fetch_energy_range", {"site_id": "FJJB000001", "items": [], "total_days": 0}, {}),
            ("export_data_table", card, {"title": "测试卡片"}),
        ]
        updates = UIRouterSkill().execute(tool_results, {})
        assert "pending_data_cards" in updates
        assert updates["pending_data_cards"][0]["download"]["task_id"] == card["download"]["task_id"]


# ── GET /export/{task_id} 端点 ───────────────────────────────────────


class TestExportEndpoint:
    """/export 下载端点测试（FastAPI TestClient）。"""

    def test_download_csv(self):
        """合法 task_id → 200 text/csv，内容与落盘文件一致。"""
        from fastapi.testclient import TestClient
        from src.services.api import app

        card = export_data_table(
            "端点测试",
            [{"key": "a", "label": "A", "unit": ""}],
            [{"a": 1}],
        )
        task_id = card["download"]["task_id"]

        client = TestClient(app)
        r = client.get(f"/export/{task_id}")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/csv")
        assert "A" in r.text
        assert "1" in r.text

    def test_missing_file_404(self):
        """合法 hex 格式但文件不存在 → 404。"""
        from fastapi.testclient import TestClient
        from src.services.api import app

        client = TestClient(app)
        r = client.get(f"/export/{'0' * 32}")
        assert r.status_code == 404

    def test_invalid_task_id_400(self):
        """含非 hex 字符的 task_id → 400。"""
        from fastapi.testclient import TestClient
        from src.services.api import app

        client = TestClient(app)
        r = client.get("/export/nonexistent123")
        assert r.status_code == 400

    @pytest.mark.parametrize("bad", ["..%2F..%2Fetc%2Fpasswd", "abc", "with-dash"])
    def test_traversal_blocked(self, bad):
        """路径穿越 / 非法字符 → 永不 200。"""
        from fastapi.testclient import TestClient
        from src.services.api import app

        client = TestClient(app)
        r = client.get(f"/export/{bad}")
        assert r.status_code != 200


# ── SSE event: data_card ─────────────────────────────────────────────


class _FakeGraph:
    """假 graph：astream_events 产出预设事件序列。"""

    def __init__(self, events):
        self._events = events

    async def astream_events(self, state, config=None, version="v2"):
        for ev in self._events:
            yield ev


class TestSSEDataCardEvent:
    """SSE /stream 推送 data_card 事件测试（mock graph，不依赖 LLM）。"""

    def test_stream_emits_data_card(self, monkeypatch):
        """on_chain_end 携带 pending_data_cards → /stream 推送 event: data_card。"""
        from fastapi.testclient import TestClient
        import src.services.api as api_module

        # 生成一张真实 DataCard 作为 pending_data_cards
        card = export_data_table(
            "SSE 测试卡片",
            [{"key": "date", "label": "日期", "unit": ""}],
            [{"date": "2026-06-20"}],
        )
        fake_event = {
            "event": "on_chain_end",
            "data": {"output": {"pending_data_cards": [card]}},
            "metadata": {"langgraph_node": "v3_engine_router"},
        }
        monkeypatch.setattr(api_module, "graph", _FakeGraph([fake_event]))

        client = TestClient(app=api_module.app)
        r = client.post(
            "/stream",
            json={"user_input": "导出最近7天能耗数据", "thread_id": "test-sse-1"},
        )
        assert r.status_code == 200
        body = r.text
        assert "event: data_card" in body
        # data 行包含卡片标题与 download URL
        assert "SSE 测试卡片" in body
        assert f"/export/{card['download']['task_id']}" in body
        # 流以 done 结束
        assert "event: done" in body

    def test_stream_no_data_card_when_empty(self, monkeypatch):
        """无 pending_data_cards 的 on_chain_end → 不推送 data_card 事件。"""
        from fastapi.testclient import TestClient
        import src.services.api as api_module

        fake_event = {
            "event": "on_chain_end",
            "data": {"output": {"final_report": "无导出"}},
            "metadata": {},
        }
        monkeypatch.setattr(api_module, "graph", _FakeGraph([fake_event]))

        client = TestClient(app=api_module.app)
        r = client.post(
            "/stream",
            json={"user_input": "今天天气", "thread_id": "test-sse-2"},
        )
        assert r.status_code == 200
        assert "event: data_card" not in r.text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
