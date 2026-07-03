"""chart_recommender — 基于真实表格字段结构推荐图表

所属层：utils
依赖：datetime, src.schemas.data_card
对接算法层：N/A
"""
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Sequence

from src.schemas.data_card import ChartAxis, ChartSeries, ChartSpec, ColumnDef

_TIME_TOKENS = ("date", "time", "day", "month", "year", "日期", "时间", "日", "月", "年")
_COMPOSITION_TOKENS = ("占比", "构成", "份额", "比例", "分布", "composition", "share", "ratio")
_RANKING_TOKENS = ("排名", "排行", "rank", "top")
_VALID_HINTS = {"auto", "trend", "comparison", "composition", "donut", "none"}
_MAX_SERIES = 4
_DONUT_TOKENS = ("环形图", "环图", "donut")


def _is_number(value: Any) -> bool:
    """判断值是否为可绘图数值，排除布尔值。"""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _looks_like_time(column: ColumnDef, values: Sequence[Any]) -> bool:
    """根据字段语义和样本值识别时间维度。"""
    descriptor = f"{column.key} {column.label}".lower()
    if any(token in descriptor for token in _TIME_TOKENS):
        return True
    non_empty = [value for value in values if value not in (None, "")]
    if not non_empty:
        return False
    for value in non_empty:
        if isinstance(value, (date, datetime)):
            continue
        if not isinstance(value, str):
            return False
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return False
    return True


def _select_compatible_series(columns: List[ColumnDef]) -> tuple[List[ColumnDef], int]:
    """选择同一单位且不超过上限的数值序列。

    Args:
        columns: 候选数值列，顺序代表展示优先级。

    Returns:
        可安全同图展示的列，以及被排除的列数。
    """
    if not columns:
        return [], 0
    primary_unit = columns[0].unit
    compatible = [column for column in columns if column.unit == primary_unit]
    selected = compatible[:_MAX_SERIES]
    return selected, len(columns) - len(selected)


def recommend_chart(
    title: str,
    columns: List[ColumnDef],
    rows: List[Dict[str, Any]],
    chart_hint: str = "auto",
) -> Optional[ChartSpec]:
    """依据列结构和提示推荐图表，不修改或派生任何业务数据。

    Args:
        title: 数据卡片标题，用于识别明确的构成语义。
        columns: 已验证的表格列定义。
        rows: 图表、表格和 CSV 共用的真实数据行。
        chart_hint: auto/trend/comparison/composition/donut/none。

    Returns:
        可渲染的 ChartSpec；数据不足或不适合绘图时返回 None。

    Raises:
        ValueError: chart_hint 不在支持范围内。
    """
    if chart_hint not in _VALID_HINTS:
        raise ValueError(f"不支持的 chart_hint: {chart_hint}")
    if chart_hint == "none" or len(rows) < 2 or len(columns) < 2:
        return None

    numeric_columns = [
        column
        for column in columns
        if any(_is_number(row.get(column.key)) for row in rows)
        and all(row.get(column.key) in (None, "") or _is_number(row.get(column.key)) for row in rows)
    ]
    if not numeric_columns:
        return None

    dimension_columns = [column for column in columns if column.key not in {item.key for item in numeric_columns}]
    time_column = next(
        (
            column
            for column in dimension_columns
            if _looks_like_time(column, [row.get(column.key) for row in rows])
        ),
        None,
    )
    category_column = next(
        (column for column in dimension_columns if any(row.get(column.key) not in (None, "") for row in rows)),
        None,
    )

    chart_type: Optional[str] = None
    axis: Optional[ColumnDef] = None
    reason = ""
    title_has_composition = any(token in title.lower() for token in _COMPOSITION_TOKENS)

    if chart_hint == "trend" or (chart_hint == "auto" and time_column is not None):
        if time_column is not None:
            chart_type, axis = "line", time_column
            reason = "时间维度配合连续数值，适合展示变化趋势"
    elif chart_hint in {"composition", "donut"} or (chart_hint == "auto" and title_has_composition):
        if category_column is not None:
            wants_donut = chart_hint == "donut" or any(token in title.lower() for token in _DONUT_TOKENS)
            chart_type, axis = "donut" if wants_donut else "pie", category_column
            numeric_columns = numeric_columns[:1]
            reason = "数据表达整体构成或份额，适合用环形图展示各分类占比" if wants_donut else "数据表达整体构成或份额，适合展示各分类占比"
    elif chart_hint in {"comparison", "auto"} and category_column is not None:
        chart_type, axis = "bar", category_column
        reason = "分类维度配合数值，适合比较不同类别"

    if chart_type is None or axis is None:
        return None
    numeric_columns, excluded_count = _select_compatible_series(numeric_columns)
    if not numeric_columns:
        return None
    if excluded_count:
        reason += f"；为保证可读性，仅展示同单位的前 {_MAX_SERIES} 个序列"
    is_ranking = chart_type == "bar" and any(token in title.lower() for token in _RANKING_TOKENS)
    if is_ranking:
        reason += "；按数值降序展示排名并高亮第一名"
    return ChartSpec(
        type=chart_type,
        x_axis=ChartAxis(key=axis.key, label=axis.label, unit=axis.unit),
        series=[ChartSeries(key=item.key, label=item.label, unit=item.unit) for item in numeric_columns],
        reason=reason,
        sort="desc" if is_ranking else "none",
        show_values=chart_type == "bar",
        highlight_top=is_ranking,
        show_legend=len(numeric_columns) > 1 and chart_type not in {"pie", "donut"},
        show_labels=chart_type in {"pie", "donut"},
        x_label_angle=-45 if chart_type == "bar" else 0,
    )
