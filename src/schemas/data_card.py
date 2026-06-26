"""data_card — 数据卡片 Pydantic 模型（表格 + 下载信息）

所属层：schemas
依赖：pydantic
对接算法层：N/A

Phase 6 数据导出：export_data_table 工具生成 DataCard，经 SSE event: data_card
下发前端，前端渲染表格 + 下载按钮。DataCard 为通用结构，可承载任意列/行数据，
新增可导出数据类型无需改动本模型。
"""
from typing import Any, Dict, List

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


class DownloadInfo(BaseModel):
    """下载信息：指向 /export/{task_id} 端点。"""

    format: str = Field(default="csv", description="文件格式：csv")
    filename: str = Field(..., description="下载文件名（如 energy_2026-06-20.csv）")
    url: str = Field(..., description="下载 URL（/export/{task_id}）")
    task_id: str = Field(..., description="导出任务 ID（uuid4）")


class DataCard(BaseModel):
    """数据卡片：前端渲染表格 + 下载按钮。

    本期仅实现 table + download；card_type 预留 chart 扩展位（未来可视化）。
    """

    card_type: str = Field(default="table", description="卡片类型：table（未来可扩展 chart）")
    title: str = Field(..., description="卡片标题（如 FJJB000001 近7天能耗汇总）")
    table: TableData = Field(..., description="表格数据")
    download: DownloadInfo = Field(..., description="下载信息")
