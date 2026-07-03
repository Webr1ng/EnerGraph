"""app — 青山大模型决策层 + HVAC 知识库 Streamlit 演示前端

所属层：frontend
依赖：streamlit, src.graph.builder
对接算法层：N/A（通过 graph 间接调用）
"""
import sys
import uuid
from pathlib import Path

_src_root = Path(__file__).resolve().parents[2]
if str(_src_root) not in sys.path:
    sys.path.insert(0, str(_src_root))

import streamlit as st

from src.config.settings import settings
from src.graph.builder import build_graph_config, graph


def _build_route_names() -> dict:
    """从 routes.yaml 动态构建路由→名称映射。

    Returns:
        {route_path: display_name, ...}
    """
    route_names = {}
    routes_config = settings.routes
    all_routes = routes_config.get("accessible_routes", []) + routes_config.get("restricted_routes", [])
    for route in all_routes:
        route_names[route["path"]] = route["name"]
    return route_names


# 启动时从 routes.yaml 构建一次
_ROUTE_NAMES = _build_route_names()

# Phase 6 导出文件落盘目录（与 services/api.py 同路径，data/ 已 gitignore）
_EXPORT_DIR = Path(__file__).resolve().parents[2] / "data" / "exports"


def _render_data_card(card: dict) -> None:
    """渲染数据卡片：图表 + 表格 + 下载按钮（Phase 6 数据导出）。

    Args:
        card: DataCard dict（含 title / table{columns,rows} / download{task_id,filename}）
    """
    import pandas as pd  # streamlit 依赖 pandas，局部导入避免模块加载期开销

    table = card.get("table", {}) or {}
    columns = table.get("columns", []) or []
    rows = table.get("rows", []) or []
    title = card.get("title", "数据导出")
    download = card.get("download", {}) or {}
    task_id = download.get("task_id", "")
    filename = download.get("filename") or f"{task_id}.csv"
    chart = card.get("chart")

    st.markdown(f"**📊 {title}**")
    if chart and rows:
        chart_type = chart.get("type")
        x_axis = chart.get("x_axis", {}) or {}
        series = chart.get("series", []) or []
        x_key = x_axis.get("key")
        if chart_type in {"line", "bar"} and x_key and series:
            chart_rows = [dict(row) for row in rows]
            if chart_type == "bar" and chart.get("sort") in {"asc", "desc"}:
                value_key = series[0].get("key")
                chart_rows.sort(
                    key=lambda row: row.get(value_key) if isinstance(row.get(value_key), (int, float)) else float("-inf"),
                    reverse=chart.get("sort") == "desc",
                )
            for index, row in enumerate(chart_rows):
                row["__is_top"] = index == 0
            layers = []
            for item in series:
                color_encoding = {
                    "condition": {"test": "datum.__is_top", "value": "#F59E0B"},
                    "value": "#2563EB",
                } if chart.get("highlight_top") else {
                    "datum": item.get("label", item.get("key")),
                    "legend": None if not chart.get("show_legend", True) else {},
                }
                layers.append(
                    {
                        "mark": {"type": chart_type, "point": chart_type == "line"},
                        "encoding": {
                            "x": {
                                "field": x_key,
                                "type": "temporal" if chart_type == "line" else "nominal",
                                "title": x_axis.get("label", x_key),
                                "axis": {"labelAngle": chart.get("x_label_angle", 0)},
                            },
                            "y": {"field": item.get("key"), "type": "quantitative", "title": item.get("label", item.get("key"))},
                            "color": color_encoding,
                        },
                    }
                )
                if chart_type == "bar" and chart.get("show_values"):
                    layers.append(
                        {
                            "mark": {"type": "text", "dy": -8, "fontWeight": "bold"},
                            "encoding": {
                                "x": {"field": x_key, "type": "nominal", "axis": {"labelAngle": chart.get("x_label_angle", 0)}},
                                "y": {"field": item.get("key"), "type": "quantitative"},
                                "text": {"field": item.get("key"), "type": "quantitative", "format": ",.2f"},
                            },
                        }
                    )
            st.vega_lite_chart(chart_rows, {"layer": layers}, use_container_width=True)
        elif chart_type in {"pie", "donut"} and x_key and series:
            item = series[0]
            value_key = item.get("key")
            total = sum(
                row.get(value_key, 0)
                for row in rows
                if isinstance(row.get(value_key), (int, float))
            )
            pie_rows = [dict(row) for row in rows]
            for row in pie_rows:
                value = row.get(value_key, 0)
                percentage = value / total * 100 if total and isinstance(value, (int, float)) else 0
                row["__chart_label"] = f"{row.get(x_key, '')} {percentage:.1f}%"
            arc_mark = {
                "type": "arc",
                "tooltip": True,
                "innerRadius": 90 if chart_type == "donut" else 0,
            }
            pie_layers = [
                {
                    "mark": arc_mark,
                    "encoding": {
                        "theta": {"field": item.get("key"), "type": "quantitative", "stack": True},
                        "color": {
                            "field": x_key,
                            "type": "nominal",
                            "title": x_axis.get("label", x_key),
                            "legend": {"orient": "top"} if chart.get("show_legend", True) else None,
                        },
                        "tooltip": [
                            {"field": x_key, "type": "nominal", "title": x_axis.get("label", x_key)},
                            {"field": item.get("key"), "type": "quantitative", "title": item.get("label", item.get("key"))},
                        ],
                    },
                }
            ]
            if chart.get("show_labels"):
                pie_layers.append(
                    {
                        "mark": {"type": "text", "radiusOffset": 18, "fontWeight": "bold"},
                        "encoding": {
                            "theta": {"field": item.get("key"), "type": "quantitative", "stack": True},
                            "text": {"field": "__chart_label", "type": "nominal"},
                            "color": {"value": "#374151"},
                        },
                    }
                )
            st.vega_lite_chart(
                pie_rows,
                {"layer": pie_layers},
                use_container_width=True,
            )
        if chart.get("reason"):
            st.caption(f"推荐理由：{chart['reason']}")
    if rows:
        df = pd.DataFrame(rows)
        if columns:
            # 按 columns 顺序重排列，并用中文 label 重命名表头
            col_keys = [c.get("key") for c in columns if c.get("key") in df.columns]
            if col_keys:
                df = df[col_keys]
            rename = {c.get("key"): c.get("label", c.get("key")) for c in columns if c.get("key") in df.columns}
            df = df.rename(columns=rename)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("（无数据行）")

    csv_path = _EXPORT_DIR / f"{task_id}.csv"
    if csv_path.is_file():
        with open(csv_path, "rb") as f:
            csv_bytes = f.read()
        st.download_button(
            label="⬇️ 下载 CSV",
            data=csv_bytes,
            file_name=filename,
            mime="text/csv",
            key=f"dl_{task_id}",
        )
    else:
        st.warning("导出文件不存在或已过期")

st.set_page_config(page_title="青山大模型决策层演示", layout="wide")
st.title("青山大模型决策层演示")
st.caption("暖通空调专家问答 · 福加运营数据查询 · 基于 LangGraph + DeepSeek V4")

NODE_STEPS = {
    "cognitive_parser": "意图解析 — 分析问题类型，选择工具",
    "v3_engine_router": "工具调用 — 检索知识库 / 查询引擎数据",
    "interpreter_generator": "生成回答 — 综合数据，撰写报告",
}

# 初始化对话历史
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "thread_id" not in st.session_state:
    st.session_state.thread_id = f"streamlit-{uuid.uuid4().hex}"
if "validation_cards" not in st.session_state:
    st.session_state.validation_cards = []

# 侧边栏
with st.sidebar:
    st.header("配置")
    from datetime import datetime
    current_date = datetime.now().strftime("%Y-%m-%d")
    target_date = st.text_input("目标日期（调度场景）", value=current_date)
    st.divider()
    st.markdown("**🔮 预测接口测试（光伏/冷负荷/电负荷）**")
    forecast_examples = [
        "今天光伏预测准不准？准确率多少？",            # 光伏预测(单日, fetch_pv_forecast → /analysis/pv-forecast)
        "冷负荷预测今天多少？平均偏差大吗？",          # 冷负荷预测(单日, fetch_load_forecast → /analysis/load-forecast)
        "电负荷预测今天多少？当前和预测负荷差多少？",  # 电负荷预测(单日, fetch_electricity_forecast → /analysis/electricity-forecast)
        "今天负荷预测情况怎么样？",                    # 泛问→多意图同返(冷+电双工具+两个跳转)
    ]
    for ex in forecast_examples:
        if st.button(ex, use_container_width=True, key=f"fc_{ex[:20]}"):
            st.session_state.pending_input = ex

    st.markdown("**通用 HVAC（测试 RAG）**")
    hvac_examples = [
        "含湿量与相对湿度有何区别？在工程计算中如何选用？",
        "已知一台离心机组，负载率93%，冷却水进水温度33℃，分析其能效表现",
        "冷冻水系统出现压差异常如何诊断？",
        "地铁车站环控系统如何节能优化？",
    ]
    for ex in hvac_examples:
        if st.button(ex, use_container_width=True, key=f"hvac_{ex[:20]}"):
            st.session_state.pending_input = ex

    st.markdown("**多意图测试**")
    multi_intent_examples = [
        "查一下今天的光伏发电量，顺便看看今天的能耗汇总",
        "冷水机房 COP 多少？有没有报警？",
        "帮我查一下今天的能耗，再看看光伏发电情况",
        "查 COP，导出近十天能耗，看看有没有报警",
    ]
    for ex in multi_intent_examples:
        if st.button(ex, use_container_width=True, key=f"multi_{ex[:20]}"):
            st.session_state.pending_input = ex

    st.markdown("**📊 数据导出测试（Phase 6）**")
    export_examples = [
        "导出最近7天的能耗数据",                       # 能耗导出(经典)
        "导出最近7天光伏预测数据",                     # 光伏预测导出(fetch_pv_forecast_range)
        "导出最近7天冷负荷预测数据",                   # 冷负荷预测导出(fetch_load_forecast_range)
        "导出最近7天电负荷预测数据",                   # 电负荷预测导出(fetch_electricity_forecast_range)
        "导出最近7天负荷预测数据",                     # 泛问→多意图双 CSV 双跳(冷+电)
    ]
    for ex in export_examples:
        if st.button(ex, use_container_width=True, key=f"exp_{ex[:20]}"):
            st.session_state.pending_input = ex

    st.markdown("**图表本地验证**")
    if st.button("生成折线图验证卡片", use_container_width=True):
        from src.tools.export_data import export_data_table

        st.session_state.validation_cards.append(
            export_data_table(
                "近3天能耗趋势",
                [
                    {"key": "date", "label": "日期", "unit": ""},
                    {"key": "energy", "label": "总用电量", "unit": "kWh"},
                ],
                [
                    {"date": "2026-07-01", "energy": 3200},
                    {"date": "2026-07-02", "energy": 3450},
                    {"date": "2026-07-03", "energy": 3310},
                ],
                filename="chart_line_validation.csv",
                chart_hint="trend",
            )
        )
    if st.button("生成饼图验证卡片", use_container_width=True):
        from src.tools.export_data import export_data_table

        st.session_state.validation_cards.append(
            export_data_table(
                "能源构成占比",
                [
                    {"key": "source", "label": "能源类型", "unit": ""},
                    {"key": "energy", "label": "电量", "unit": "kWh"},
                ],
                [
                    {"source": "电网", "energy": 6200},
                    {"source": "光伏", "energy": 2800},
                    {"source": "储能", "energy": 1000},
                ],
                filename="chart_pie_validation.csv",
                chart_hint="composition",
            )
        )
    if st.button("生成环形图验证卡片", use_container_width=True):
        from src.tools.export_data import export_data_table

        st.session_state.validation_cards.append(
            export_data_table(
                "能源构成环形图",
                [
                    {"key": "source", "label": "能源类型", "unit": ""},
                    {"key": "energy", "label": "电量", "unit": "kWh"},
                ],
                [
                    {"source": "电网取电", "energy": 1300},
                    {"source": "光伏发电", "energy": 57},
                    {"source": "储能放电", "energy": 264},
                ],
                filename="energy_composition_donut.csv",
                chart_hint="donut",
            )
        )
    if st.button("生成排名柱状图验证卡片", use_container_width=True):
        from src.tools.export_data import export_data_table

        st.session_state.validation_cards.append(
            export_data_table(
                "本月设备用电量排名",
                [
                    {"key": "device", "label": "设备/区域", "unit": ""},
                    {"key": "energy", "label": "本月用电量", "unit": "kWh"},
                ],
                [
                    {"device": "冷水机房#1", "energy": 1950},
                    {"device": "办公楼办公和照明", "energy": 1600},
                    {"device": "办公楼空调", "energy": 2440},
                    {"device": "生产厂房空调", "energy": 1955},
                    {"device": "综合楼办公和照明", "energy": 1620},
                ],
                filename="device_energy_ranking.csv",
                chart_hint="comparison",
            )
        )

    st.markdown("**🧠 记忆模块测试（L2 长期记忆）**")
    memory_examples = [
        "记住：我的报告偏好是先给结论再给数据",          # save_memory(user_preference)
        "你记得我的报告偏好吗？",                        # search_relevant_memory(跨会话偏好)
        "这个站点有什么运行安全约束？",                  # search_relevant_memory(safety_constraint/site_fact)
        "你记得我们之前讨论的储能调度策略吗？",          # search_relevant_memory(decision_history)
    ]
    for ex in memory_examples:
        if st.button(ex, use_container_width=True, key=f"mem_{ex[:20]}"):
            st.session_state.pending_input = ex

    if st.button("清空对话", type="secondary", use_container_width=True):
        st.session_state.chat_history = []
        st.session_state.validation_cards = []
        st.rerun()

for validation_card in st.session_state.validation_cards:
    _render_data_card(validation_card)

# 显示历史对话（步骤/意图/来源折叠，回答在下）
for msg in st.session_state.chat_history:
    with st.chat_message(msg["role"]):
        if msg["role"] == "assistant":
            # 1. 思考过程 + 意图识别（折叠）
            has_steps = bool(msg.get("steps"))
            has_intent = bool(msg.get("intent_display"))
            if has_steps or has_intent:
                with st.expander("💭 思考过程 & 意图识别", expanded=False):
                    if has_steps:
                        st.markdown("\n".join(msg["steps"]))
                    if has_intent:
                        st.markdown("**🧩 识别到多个意图：**")
                        for item in msg["intent_display"]:
                            st.markdown(f"- {item}")
            # 2. 工具详情 / RAG 来源（折叠）
            if msg.get("details"):
                with st.expander("📋 工具调用详情 & 知识库来源", expanded=False):
                    for label, data in msg["details"].items():
                        st.subheader(label)
                        st.json(data)
        # 3. 回答内容（含底部跳转链接）
        st.markdown(msg["content"])
        # 4. 数据卡片（Phase 6 导出：表格 + 下载按钮，跨 rerun 持久）
        for card in msg.get("data_cards") or []:
            _render_data_card(card)

# 处理侧边栏示例按钮触发
if "pending_input" in st.session_state:
    user_input = st.session_state.pop("pending_input")
else:
    user_input = st.chat_input("输入问题或业务意图（如：冷水机组COP如何计算？）")

if user_input:
    # 显示用户消息
    st.session_state.chat_history.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    # 调用 Agent（token 级流式）
    with st.chat_message("assistant"):
        try:
            full_input = f"{user_input}\n[target_date={target_date}]"

            steps_ph = st.empty()           # 最上：ReAct 步骤
            details_ph = st.empty()        # 中间：工具/RAG 详情（在回答上方）
            answer_ph = st.empty()         # 最下：最终回答

            answer_text = ""
            steps = []
            result = {}
            tool_names = []
            seen_nodes = set()
            current_node = None
            tools_have_run = False  # 追踪工具是否已执行，用于控制流式内容路由

            for event in graph.stream(
                {
                    "user_input": full_input,
                    "thread_id": st.session_state.thread_id,
                    "page_context": {
                        "current_route": "/index/index",
                        "site_id": "FJJB000001",  # 江北工厂站点ID
                    }
                },
                config=build_graph_config(st.session_state.thread_id),
                stream_mode=["updates", "messages"],
            ):
                mode, data = event

                if mode == "messages":
                    chunk, meta = data
                    node = meta.get("langgraph_node", "")

                    # 节点切换时更新步骤
                    if node and node != current_node:
                        current_node = node
                        if node not in seen_nodes:
                            seen_nodes.add(node)
                            if node in NODE_STEPS:
                                label = NODE_STEPS[node]
                                if node == "v3_engine_router" and tool_names:
                                    label += f"（{', '.join(tool_names)}）"
                                steps.append(f"✅ {label}")
                                steps_ph.markdown("\n".join(steps))

                    # 检测工具调用
                    if hasattr(chunk, "tool_call_chunks") and chunk.tool_call_chunks:
                        for tc in chunk.tool_call_chunks:
                            if tc.get("name") and tc["name"] not in tool_names:
                                tool_names.append(tc["name"])

                    # 流式文本
                    content = chunk.content if hasattr(chunk, "content") and chunk.content else ""
                    if content:
                        if node == "interpreter_generator":
                            # interpreter 生成的内容直接进入回答区
                            answer_text += content
                            answer_ph.markdown(answer_text + "▌")
                        elif node == "cognitive_parser" and tools_have_run:
                            # 工具已执行，cognitive_parser 基于工具结果生成回答 → 流式输出
                            answer_text += content
                            answer_ph.markdown(answer_text + "▌")

                elif mode == "updates":
                    if not isinstance(data, dict):
                        continue
                    for node_name, update in data.items():
                        if not isinstance(update, dict):
                            continue
                        # 标记工具已执行
                        if node_name == "v3_engine_router":
                            tools_have_run = True
                        # 确保节点出现在步骤中
                        if node_name not in seen_nodes:
                            seen_nodes.add(node_name)
                            if node_name in NODE_STEPS:
                                label = NODE_STEPS[node_name]
                                if node_name == "v3_engine_router" and tool_names:
                                    label += f"（{', '.join(tool_names)}）"
                                steps.append(f"✅ {label}")
                                steps_ph.markdown("\n".join(steps))
                        # 合并结果
                        for k, v in update.items():
                            if k not in ("messages",):
                                result[k] = v

            # ========== 流式结束后的布局：折叠过程信息，突出回答 ==========

            # 1. 解析多意图计划（Phase 7）
            intent_plan = result.get("intent_plan")
            intent_items = []
            if intent_plan:
                for i in intent_plan:
                    if isinstance(i, dict):
                        desc = i.get("description", "")
                        cat = i.get("category", "")
                        status = i.get("status", "")
                    else:
                        desc, cat, status = i.description, i.category, i.status
                    emoji = {"monitor": "📡", "hvac": "❄️", "energy": "⚡", "alarm": "🚨", "export": "📊"}.get(cat, "📌")
                    intent_items.append(f"{emoji} 意图 {i.id if not isinstance(i, dict) else i.get('id', '?')}: {desc}")

            # 2. 将步骤 + 意图识别折叠（替换流式时的实时显示）
            if steps or intent_items:
                with steps_ph.container():
                    with st.expander("💭 思考过程 & 意图识别", expanded=False):
                        if steps:
                            st.markdown("\n".join(steps))
                        if intent_items:
                            st.markdown("**🧩 识别到多个意图：**")
                            for item in intent_items:
                                st.markdown(f"- {item}")
            else:
                steps_ph.empty()

            # 3. 页面跳转建议（Phase 2，保持可见）
            pending_actions = result.get("pending_actions", [])
            if pending_actions:
                with details_ph.container():
                    st.markdown("**🔗 Agent 建议跳转：**")
                    for action in pending_actions:
                        if isinstance(action, dict):
                            route = action.get("route", "")
                            name = action.get("name", "")
                            params = action.get("params", {})
                        else:
                            route = action.route
                            name = action.name
                            params = action.params or {}

                        # 优先使用 action 自带的 name，其次查路由表
                        route_name = name or _ROUTE_NAMES.get(route, route)

                        params = params or {}
                        param_str = ", ".join([f"{k}={v}" for k, v in params.items()])
                        st.info(f"🎯 **{route_name}** ({route})\n\n参数: {param_str}")
                    st.markdown("💡 *在福加网页中，Agent 会自动执行跳转*")

            # 4. 工具调用详情 / RAG 来源（折叠）
            details = {}
            if result.get("hvac_knowledge"):
                details["📚 HVAC 知识库检索"] = result["hvac_knowledge"]
            if result.get("constraints"):
                details["🎯 意图解析（ConstraintMatrix）"] = result["constraints"]

            if details:
                if not pending_actions:
                    # 没有跳转建议时，details_ph 用于工具详情
                    with details_ph.container():
                        with st.expander("📋 工具调用详情 & 知识库来源", expanded=False):
                            for label, data in details.items():
                                st.subheader(label)
                                st.json(data)
                else:
                    # 有跳转建议时，在跳转建议下方显示
                    with st.expander("📋 工具调用详情 & 知识库来源", expanded=False):
                        for label, data in details.items():
                            st.subheader(label)
                            st.json(data)
            elif not pending_actions:
                details_ph.empty()

            # 3. 最终回答
            final = result.get("memory_feedback") or answer_text or result.get("final_report", "（无回答）")

            # 4. 页面跳转链接（直接添加到回答末尾）
            pending_actions = result.get("pending_actions", [])
            if pending_actions:
                links = []
                for action in pending_actions:
                    route = action.route if hasattr(action, "route") else action.get("route", "")
                    action_name = action.name if hasattr(action, "name") else action.get("name", "")
                    name = action_name or _ROUTE_NAMES.get(route, route)
                    full_url = f"https://aiot-fuca.com{route}"
                    links.append(f"[{name}]({full_url})")
                final += f"\n\n---\n\n💡 **查看详细数据**：{' · '.join(links)}"

            answer_ph.markdown(final)

            # 5. 数据卡片（Phase 6 导出：表格 + 下载按钮）
            data_cards = result.get("pending_data_cards", []) or []
            for card in data_cards:
                _render_data_card(card)

            if result.get("error"):
                st.warning(f"警告: {result['error']}")

            st.session_state.chat_history.append(
                {
                    "role": "assistant",
                    "content": final,
                    "details": details,
                    "steps": steps,
                    "intent_display": intent_items if intent_plan else None,
                    "data_cards": data_cards,
                }
            )

        except Exception as e:
            import traceback
            err_detail = traceback.format_exc()
            st.error(f"运行出错: {e}")
            with st.expander("调试详情"):
                st.code(err_detail)
            st.session_state.chat_history.append(
                {"role": "assistant", "content": f"运行出错: {e}", "details": {}}
            )

        st.rerun()

st.markdown("---")
st.caption("Phase 1/2/3/7 Demo · HVAC 知识库 5605 条 · 已接入福加真实 API（能耗查询）· 支持多意图识别 + 自动跳转建议")
