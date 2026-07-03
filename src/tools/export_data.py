"""export_data — 数据导出工具（通用 CSV 生成 + DataCard 下发）

所属层：tools
依赖：csv, uuid, src.schemas.data_card
对接算法层：N/A

Phase 6 统一导出模板：LLM 取到任意多日/多行数据后调用 export_data_table，
本工具生成 CSV 临时文件并返回 DataCard（含表格 + 下载 URL）。新增可导出
数据类型无需改动本工具——只需新增对应 range fetch 工具并在 prompt 补一行。
"""
import csv
import logging
import uuid
from pathlib import Path
from typing import Any, Dict, List

from src.schemas.data_card import ColumnDef, DataCard, DownloadInfo, TableData
from src.utils.chart_recommender import recommend_chart

logger = logging.getLogger(__name__)

# 导出文件落盘目录（data/ 已 gitignore，文件不进 Git）
_EXPORT_DIR = Path(__file__).resolve().parents[2] / "data" / "exports"


def export_data_table(
    title: str,
    columns: List[Dict[str, Any]],
    rows: List[Dict[str, Any]],
    filename: str = "",
    chart_hint: str = "auto",
) -> Dict[str, Any]:
    """生成 CSV 文件并返回含自动推荐图表的 DataCard。

    通用导出工具：columns 由 LLM 给出（中文表头 + 单位），rows 为行数据。
    前端通过 SSE event: data_card 收到 DataCard 后渲染表格 + 下载按钮，
    下载链接指向 GET /export/{task_id}。

    Args:
        title: 卡片标题（如 FJJB000001 近7天能耗汇总）
        columns: 列定义列表 [{key, label, unit?}, ...]；为空时从首行 keys 推导
        rows: 行数据列表 [{key: value, ...}, ...]
        filename: 下载文件名；为空时用 {task_id}.csv
        chart_hint: 选图提示：auto/trend/comparison/composition/none

    Returns:
        DataCard 的 dict 表示；失败返回 {"error": "export_data_table: ..."}
    """
    try:
        rows = rows or []
        columns = columns or []

        # columns 为空时从首行 keys 推导（label = key）
        if not columns and rows:
            columns = [{"key": k, "label": str(k)} for k in rows[0].keys()]

        col_defs = [ColumnDef(**c) if isinstance(c, dict) else c for c in columns]

        task_id = uuid.uuid4().hex
        _EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        file_path = _EXPORT_DIR / f"{task_id}.csv"

        # 写 CSV：表头 = label（含单位），行按 key 取值
        # utf-8-sig BOM 让 Excel 正确识别中文编码
        header = [c.label + (f" ({c.unit})" if c.unit else "") for c in col_defs]
        with file_path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(header)
            for row in rows:
                writer.writerow([row.get(c.key, "") for c in col_defs])

        final_filename = filename or f"{task_id}.csv"
        chart = recommend_chart(title, col_defs, rows, chart_hint)

        card = DataCard(
            card_type="table_chart" if chart else "table",
            title=title,
            table=TableData(columns=col_defs, rows=rows),
            chart=chart,
            download=DownloadInfo(
                format="csv",
                filename=final_filename,
                url=f"/export/{task_id}",
                task_id=task_id,
            ),
        )
        logger.info(f"export_data_table: 生成 {file_path}（{len(rows)} 行）")
        return card.model_dump()
    except Exception as e:
        logger.error(f"export_data_table 失败: {e}")
        return {"error": f"export_data_table: {e}"}
