from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from testdata_tool import __version__
from testdata_tool.config import ConfigError, load_config
from testdata_tool.paths import default_template_folder
from testdata_tool.pipeline import merge_prechecked
from testdata_tool.preferences import load_preferences, save_preferences
from testdata_tool.precheck import run_precheck
from testdata_tool.query import filter_and_downsample, load_dataset


st.set_page_config(
    page_title="Testing Raw Data Consolidation",
    page_icon="📈",
    layout="wide",
)
st.markdown(
    "<style>[data-testid='stSkillsNudge']{display:none!important}</style>",
    unsafe_allow_html=True,
)


def _load_configuration():
    try:
        return load_config()
    except ConfigError as exc:
        st.error(str(exc))
        st.stop()


def _status_table(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    wanted = {
        "relative_path": "文件",
        "status": "状态",
        "test_type": "测试类型",
        "matched_fields": "命中字段数",
        "missing_fields": "缺失字段",
        "axis_columns": "横轴字段",
        "row_count": "数据行数",
        "messages": "检查信息",
    }
    columns = [column for column in wanted if column in frame.columns]
    return frame[columns].rename(columns=wanted)


def _render_chart(result, config):
    st.subheader("4. 查看与下载")
    test_type = st.selectbox("测试类型", sorted(result.datasets))
    dataset_path = result.datasets[test_type]
    frame = load_dataset(dataset_path)
    source_meta = result.source_index[result.source_index["测试类型"] == test_type]
    label_by_id = dict(zip(source_meta["Source_ID"], source_meta["相对路径"]))
    source_ids = list(label_by_id)
    selected_sources = st.multiselect(
        "来源文件",
        source_ids,
        default=source_ids,
        format_func=lambda item: label_by_id.get(item, item),
    )
    visible = [column for column in frame.columns if not column.startswith("__")]
    numeric_channels = [
        column
        for column in visible
        if column not in config.type_rules[test_type].get("axis_output", [])
        and pd.to_numeric(frame[column], errors="coerce").notna().any()
    ]
    defaults = numeric_channels[: min(4, len(numeric_channels))]
    channels = st.multiselect("通道", numeric_channels, default=defaults)
    source_filtered = frame[
        frame["__source_id"].isin(selected_sources)
        if selected_sources
        else pd.Series(False, index=frame.index)
    ]
    axis_values = source_filtered["__axis_value"].dropna()
    axis_min = axis_max = None
    if not axis_values.empty and axis_values.min() != axis_values.max():
        low, high = axis_values.min(), axis_values.max()
        if pd.api.types.is_datetime64_any_dtype(axis_values):
            low = low.to_pydatetime() if hasattr(low, "to_pydatetime") else low
            high = high.to_pydatetime() if hasattr(high, "to_pydatetime") else high
        else:
            low = low.item() if hasattr(low, "item") else low
            high = high.item() if hasattr(high, "item") else high
        bounds = (low, high)
        axis_min, axis_max = st.slider("横轴显示范围", min_value=bounds[0], max_value=bounds[1], value=bounds)
    max_points = int(config.app.get("export", {}).get("chart_max_points", 20_000))
    chart_data = filter_and_downsample(
        frame, selected_sources, axis_min, axis_max, max_points
    )
    if channels and not chart_data.empty:
        plot_frame = chart_data[["__axis_value", "__source_id", *channels]].copy()
        for channel in channels:
            plot_frame[channel] = pd.to_numeric(plot_frame[channel], errors="coerce")
        long_frame = plot_frame.melt(
            id_vars=["__axis_value", "__source_id"],
            value_vars=channels,
            var_name="通道",
            value_name="数值",
        ).dropna(subset=["数值"])
        figure = px.line(
            long_frame,
            x="__axis_value",
            y="数值",
            color="通道",
            line_group="__source_id",
            hover_data=["__source_id"],
        )
        figure.update_layout(xaxis_title="时间 / 循环 / 频率", legend_title="通道")
        figure.update_xaxes(rangeslider_visible=True)
        st.plotly_chart(figure, width="stretch")
        if len(source_filtered) > max_points:
            st.caption(f"图表显示已降采样至最多 {max_points:,} 个点，下载数据未被修改。")
    else:
        st.info("请选择至少一个来源文件和一个数值通道。")

    st.success(f"合并文件：{result.output_path}")
    size_mb = result.output_path.stat().st_size / 1024 / 1024
    if size_mb <= 500:
        st.download_button(
            "下载合并文件",
            data=result.output_path.read_bytes(),
            file_name=result.output_path.name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    else:
        st.warning(f"文件为 {size_mb:.1f} MB。为避免网页占用过多内存，请从输出目录直接打开。")
    download_columns = st.columns(2)
    download_columns[0].download_button(
        "下载验证报告",
        data=result.validation_path.read_bytes(),
        file_name=result.validation_path.name,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    download_columns[1].download_button(
        "下载处理日志",
        data=result.log_path.read_bytes(),
        file_name=result.log_path.name,
        mime="text/plain",
    )


def main():
    config = _load_configuration()
    st.title("Testing Raw Data Consolidation")
    st.caption(f"本地离线工具 · 版本 {__version__} · 黄色/绿色字段来自模板，不要求原始文件带颜色")
    with st.sidebar:
        st.markdown("### 使用顺序")
        st.markdown("1. 设置三个路径\n2. 执行 Pre-check\n3. 有效文件数大于 0 后合并\n4. 查看图表或下载")
        contact = config.app.get("contact", {})
        st.markdown("### 支持")
        st.write(contact.get("owner", "Data Tool Support"))
        st.write(contact.get("email", ""))

    preferences = load_preferences()
    default_template = default_template_folder(config)
    saved_input = preferences.get("input_folder", "")
    saved_output = preferences.get("output_folder", "")
    saved_template = preferences.get("template_folder", "")
    if saved_input and not Path(saved_input).is_absolute():
        saved_input = ""
    if saved_output and not Path(saved_output).is_absolute():
        saved_output = ""
    if not saved_template or not Path(saved_template).is_dir():
        saved_template = str(default_template)
    st.subheader("1. 路径设置")
    col1, col2, col3 = st.columns(3)
    input_value = col1.text_input("原始数据输入目录", saved_input)
    output_value = col2.text_input("合并结果输出目录", saved_output)
    template_value = col3.text_input("表头模板目录", saved_template)

    st.subheader("2. Pre-check")
    if st.button("开始 Pre-check", type="primary"):
        try:
            if not input_value.strip():
                raise ValueError("请输入原始数据输入目录")
            if not output_value.strip():
                raise ValueError("请输入合并结果输出目录")
            if not template_value.strip():
                raise ValueError("请输入表头模板目录")
            input_folder = Path(input_value).expanduser()
            output_folder = Path(output_value).expanduser()
            template_folder = Path(template_value).expanduser()
            with st.spinner("正在扫描并检查文件……"):
                result = run_precheck(input_folder, template_folder, output_folder, config)
            st.session_state["precheck"] = result
            st.session_state.pop("merge_result", None)
            save_preferences(
                {
                    "input_folder": str(input_folder),
                    "output_folder": str(output_folder),
                    "template_folder": str(template_folder),
                }
            )
        except Exception as exc:
            st.error(f"Pre-check 失败：{exc}")

    precheck = st.session_state.get("precheck")
    if precheck:
        status_frame = precheck.dataframe()
        status_counts = (
            status_frame["status"].value_counts()
            if "status" in status_frame.columns
            else pd.Series(dtype="int64")
        )
        metrics = st.columns(4)
        metrics[0].metric("扫描文件", precheck.scanned_count)
        metrics[1].metric("可合并文件", precheck.valid_count)
        metrics[2].metric("无效文件", int(status_counts.get("无效", 0)))
        metrics[3].metric("重复文件", int(status_counts.get("重复并跳过", 0)))
        st.dataframe(_status_table(status_frame), width="stretch", hide_index=True)
        with st.expander("模板高亮字段预览"):
            for test_type, template in sorted(precheck.templates.items()):
                st.markdown(f"**{test_type}** — {template.path.name}（第 {template.header_row} 行）")
                st.write("、".join(template.fields))

        st.subheader("3. 合并")
        if precheck.valid_count <= 0:
            st.warning("有效文件数为 0，不能开始合并。")
        elif st.button("开始合并", type="primary"):
            progress = st.progress(0.0, text="准备合并")

            def update(done, total, message):
                progress.progress(min(1.0, done / max(total, 1)), text=message)

            try:
                merged = merge_prechecked(
                    precheck, Path(output_value).expanduser(), config, update
                )
                st.session_state["merge_result"] = merged
                progress.progress(1.0, text="合并完成")
            except Exception as exc:
                st.error(f"合并失败：{exc}")

    merged = st.session_state.get("merge_result")
    if merged:
        _render_chart(merged, config)


main()
