"""data_card — 数据卡片 Pydantic 模型（图表 + 表格 + 下载信息）

所属层：schemas
依赖：pydantic
对接算法层：N/A

Phase 6 数据导出：export_data_table 工具生成 DataCard，经 SSE event: data_card
下发前端，前端渲染表格 + 下载按钮。DataCard 为通用结构，可承载任意列/行数据，
新增可导出数据类型无需改动本模型。
"""
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class ColumnDef(BaseModel):
    """表格列定义。

    由 LLM 在调用 export_data_table 时给出，决定 CSV 表头与取值字段。
    """

    key: str = Field(..., description="行数据中对应字段名（snake_case，如 total_consumption_kwh）")
    label: str = Field(..., description="表头显示文本（中文，如 总用电量）")
    unit: str = Field(default="", description="单位（如 kWh / ℃），可为空")


class TableData(BaseModel):
    """表格数据：列定义 + 行数据。"""

    columns: List[ColumnDef] = Field(default_factory=list, description="列定义列表")
    rows: List[Dict[str, Any]] = Field(default_factory=list, description="行数据，每行为 {key: value}")


class ChartAxis(BaseModel):
    """图表横轴或分类维度定义。"""

    key: str = Field(..., description="table.rows 中作为横轴或分类名称的字段")
    label: str = Field(..., description="前端展示名称")
    unit: str = Field(default="", description="字段单位，可为空")


class ChartSeries(BaseModel):
    """图表数值序列定义。"""

    key: str = Field(..., description="table.rows 中作为图表数值的字段")
    label: str = Field(..., description="序列展示名称")
    unit: str = Field(default="", description="数值单位，可为空")


class ChartSpec(BaseModel):
    """前端图表渲染规范，数据始终取自 DataCard.table.rows。"""

    type: Literal["line", "bar", "pie"] = Field(..., description="图表类型")
    x_axis: ChartAxis = Field(..., description="横轴或分类维度")
    series: List[ChartSeries] = Field(..., description="数值序列")
    reason: str = Field(..., description="推荐该图表的原因")


class DownloadInfo(BaseModel):
    """下载信息：指向 /export/{task_id} 端点。"""

    format: str = Field(default="csv", description="文件格式：csv")
    filename: str = Field(..., description="下载文件名（如 energy_2026-06-20.csv）")
    url: str = Field(..., description="下载 URL（/export/{task_id}）")
    task_id: str = Field(..., description="导出任务 ID（uuid4）")


class DataCard(BaseModel):
    """数据卡片：前端渲染图表、表格与下载按钮。"""

    card_type: Literal["table", "table_chart"] = Field(default="table", description="卡片类型")
    title: str = Field(..., description="卡片标题（如 FJJB000001 近7天能耗汇总）")
    table: TableData = Field(..., description="表格数据")
    chart: Optional[ChartSpec] = Field(default=None, description="自动推荐图表；不适合绘图时为空")
    download: DownloadInfo = Field(..., description="下载信息")
