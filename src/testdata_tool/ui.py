from __future__ import annotations

import os
import time
from uuid import uuid4
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from testdata_tool import __version__
from testdata_tool.charting import (
    CHART_COMPONENT_CARD_HEIGHT,
    build_chart_definitions,
    build_linked_chart_html,
    has_chart_numeric_values,
)
from testdata_tool.config import (
    ConfigError,
    is_app_update_available,
    is_app_update_required,
    load_config,
)
from testdata_tool.paths import default_template_folder
from testdata_tool.pipeline import merge_prechecked
from testdata_tool.preferences import load_preferences, save_preferences
from testdata_tool.precheck import run_precheck
from testdata_tool.query import filter_dataset, load_dataset
from testdata_tool.normalize import normalize_header
from testdata_tool.usage_logging import create_success_event, get_service


st.set_page_config(
    page_title="Testing Raw Data Consolidation",
    page_icon="📈",
    layout="wide",
)
st.markdown(
    """<style>
    [data-testid='stSkillsNudge']{display:none!important}
    .st-key-precheck_status [role='gridcell']{white-space:normal!important;line-height:1.28!important;overflow-wrap:anywhere!important}
    .st-key-precheck_status [role='columnheader']{white-space:normal!important;line-height:1.2!important}
    </style>""",
    unsafe_allow_html=True,
)


def _select_folder(widget_key: str, title: str) -> None:
    """Open a native Windows folder picker and put the result in a path widget."""
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected = filedialog.askdirectory(title=title, mustexist=True)
        root.destroy()
        if selected:
            st.session_state[widget_key] = selected
    except Exception as exc:
        st.warning(f"无法打开系统文件夹选择器，请手动输入路径：{exc}")


def _path_picker(label: str, key: str, default: str, title: str):
    """Render a path text box with a native Browse button beside it."""
    if key not in st.session_state:
        st.session_state[key] = default
    field, button = st.columns([5, 1])
    field.text_input(label, key=key)
    button.button(
        "浏览…",
        key=f"browse_{key}",
        use_container_width=True,
        on_click=_select_folder,
        args=(key, title),
    )
    return st.session_state[key]


def _load_configuration():
    try:
        with st.spinner("正在检查中央配置和标准模板……"):
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
        "messages": "检查摘要",
    }
    columns = [column for column in wanted if column in frame.columns]
    result = frame[columns].rename(columns=wanted).copy()
    if "缺失字段" in result:
        result["缺失字段"] = result["缺失字段"].map(_compact_cell_text)
    if "横轴字段" in result:
        result["横轴字段"] = result["横轴字段"].map(_compact_cell_text)
    if "检查摘要" in result:
        result["检查摘要"] = result["检查摘要"].map(_compact_message)
    return result


def _compact_cell_text(value: object, limit: int = 90) -> str:
    text = str(value or "").replace("；", "、").replace("\n", " ").strip()
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


def _compact_message(value: object) -> str:
    text = _compact_cell_text(value, limit=120)
    replacements = {
        "横轴字段存在，但样本值无法解析": "横轴样本无法解析",
        "没有匹配到任何黄色或绿色模板字段": "未匹配模板高亮字段",
        "当前不可合并": "当前格式暂不支持合并",
        "完全重复": "重复",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text


def _merge_candidate_table(precheck) -> set[str]:
    """Render an editable, default-selected list of files eligible for merging."""
    candidates = [item for item in precheck.files if item.mergeable]
    if not candidates:
        return set()
    rows = [
        {
            "合并": True,
            "文件": item.relative_path,
            "测试类型": item.test_type or "",
            "数据行数": item.row_count,
            "状态": item.status.value,
            "检查摘要": _compact_message("；".join(item.messages)),
            "_source_id": item.source_id,
        }
        for item in candidates
    ]
    revision = st.session_state.get("precheck_revision", 0)
    selected = st.data_editor(
        pd.DataFrame(rows),
        key=f"merge_candidates_{revision}",
        width="stretch",
        hide_index=True,
        height=min(420, max(120, 42 * (len(rows) + 1))),
        row_height=42,
        disabled=["文件", "测试类型", "数据行数", "状态", "检查摘要", "_source_id"],
        column_order=["合并", "文件", "测试类型", "数据行数", "状态", "检查摘要"],
        column_config={
            "合并": st.column_config.CheckboxColumn("合并", help="取消勾选可排除该文件", width="small"),
            "文件": st.column_config.TextColumn("文件", width="large"),
            "测试类型": st.column_config.TextColumn("测试类型", width="small"),
            "数据行数": st.column_config.NumberColumn("数据行数", format="%d", width="small"),
            "状态": st.column_config.TextColumn("状态", width="medium"),
            "检查摘要": st.column_config.TextColumn("检查摘要", width="large"),
        },
    )
    return set(selected.loc[selected["合并"], "_source_id"])


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
    # Axes can appear under their raw candidate name (for example
    # ``Timestamp [ms]``) as well as the configured output name.  Neither
    # belongs in the signal picker or in the non-temperature chart.
    rule = config.type_rules[test_type]
    axis_names = {
        normalize_header(value)
        for value in [*rule.get("axis_output", []), *rule.get("axis_candidates", [])]
    }
    numeric_channels = [
        column
        for column in visible
        if normalize_header(column) not in axis_names
        and has_chart_numeric_values(frame[column])
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
    chart_data = (
        filter_dataset(frame, selected_sources, axis_min, axis_max)
        if selected_sources
        else frame.iloc[0:0]
    )
    if channels and not chart_data.empty:
        chart_definitions = build_chart_definitions(
            chart_data, channels, config.app.get("temperature", {})
        )
        if chart_definitions:
            # Leave room below all Plotly cards for the component's PNG button.
            chart_height = len(chart_definitions) * CHART_COMPONENT_CARD_HEIGHT + 58
            components.html(
                build_linked_chart_html(
                    chart_definitions,
                    cycles_quick_export=(
                        config.type_rules[test_type].get("time_basis") == "cycles"
                    ),
                ),
                height=chart_height,
                scrolling=False,
            )
        else:
            st.info("所选通道没有可显示的数值。")
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
    usage = None
    try:
        usage = get_service(config.app.get("usage_logging", {}))
        usage_key = (str(usage.outbox.path), usage.settings)
        if st.session_state.get("usage_initialized") != usage_key:
            usage.wake()
            st.session_state["usage_initialized"] = usage_key
    except Exception:
        st.warning("使用记录缓存不可用；本次成功记录可能无法保存。")
    brand_title = config.app.get("ui", {}).get(
        "brand_title", "Testing Raw Data Consolidation"
    )
    st.title(brand_title)
    st.caption(
        f"程序 {__version__} · 配置 {config.config_version} · 模板 {config.template_version}"
        f" · 配置来源 {config.config_source}"
    )
    for warning in config.warnings:
        st.warning(warning)
    if config.template_updated:
        message = config.app.get("managed_templates", {}).get(
            "success_message", "标准模板已更新至版本 {version}"
        )
        st.success(str(message).format(version=config.template_version))
    announcement = config.app.get("ui", {}).get("announcement", "")
    if announcement:
        st.info(announcement)

    update_required = is_app_update_required(config)
    update_available = is_app_update_available(config)
    if update_required or update_available:
        message = (
            f"当前程序版本 {__version__}，最新版本 {config.latest_app_version}，"
            f"最低支持版本 {config.minimum_app_version}。"
        )
        if update_required:
            st.error(f"{message}请从公共盘复制新版程序后再继续。")
        else:
            st.warning(f"{message}建议升级，新版本发布前当前程序仍可继续使用。")
        if config.release_note:
            st.caption(config.release_note)
        if config.app_download_path and st.button("打开新版程序位置", key="open_app_release"):
            try:
                os.startfile(str(Path(config.app_download_path).parent))  # type: ignore[attr-defined]
            except Exception as exc:
                st.error(f"无法打开公共盘位置：{exc}")
    if update_required:
        st.stop()
    with st.sidebar:
        st.markdown("### 使用顺序")
        st.markdown("1. 设置三个路径\n2. 执行 Pre-check\n3. 有效文件数大于 0 后合并\n4. 查看图表或下载")
        contact = config.app.get("contact", {})
        st.markdown("### 支持")
        st.write(contact.get("owner", "Data Tool Support"))
        st.write(contact.get("email", ""))
        if contact.get("phone"):
            st.write(contact["phone"])
        if contact.get("note"):
            st.caption(contact["note"])
        help_text = config.app.get("ui", {}).get("help_text", "")
        if help_text:
            st.info(help_text)
        for label, url in (
            ("用户指南", config.app.get("support_links", {}).get("user_guide", "")),
            ("问题反馈", config.app.get("support_links", {}).get("issue_form", "")),
        ):
            if str(url).startswith(("https://", "http://")):
                st.link_button(label, str(url), use_container_width=True)
        if config.template_bundle and config.template_bundle.is_file():
            label = config.app.get("managed_templates", {}).get(
                "download_label", "下载当前标准模板包"
            )
            st.download_button(
                str(label),
                data=config.template_bundle.read_bytes(),
                file_name=f"Standard Templates {config.template_version}.zip",
                mime="application/zip",
            )

    preferences = load_preferences()
    configured_defaults = config.app.get("defaults", {})
    default_template = default_template_folder(config)
    saved_input = preferences.get("input_folder", "") or configured_defaults.get(
        "input_folder", ""
    )
    saved_output = preferences.get("output_folder", "") or configured_defaults.get(
        "output_folder", ""
    )
    saved_template = preferences.get("template_folder", "") or configured_defaults.get(
        "template_folder", ""
    )
    if saved_input and not Path(saved_input).is_absolute():
        saved_input = ""
    if saved_output and not Path(saved_output).is_absolute():
        saved_output = ""
    if config.managed_template_folder:
        saved_template = str(default_template)
    elif not saved_template or not Path(saved_template).is_dir():
        saved_template = str(default_template)
    st.subheader("1. 路径设置")
    col1, col2, col3 = st.columns(3)
    with col1:
        input_value = _path_picker(
            "原始数据输入目录",
            "input_folder",
            saved_input,
            "选择原始数据输入目录",
        )
    with col2:
        output_value = _path_picker(
            "合并结果输出目录",
            "output_folder",
            saved_output,
            "选择合并结果输出目录",
        )
    with col3:
        if config.managed_template_folder:
            template_value = st.text_input(
                "受管标准模板目录",
                value=str(default_template),
                disabled=True,
                key="managed_template_folder",
            )
            st.caption(f"由中央配置管理 · 模板版本 {config.template_version}")
        else:
            template_value = _path_picker(
                "表头模板目录",
                "template_folder",
                saved_template,
                "选择表头模板目录",
            )

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
            st.session_state["precheck_revision"] = (
                st.session_state.get("precheck_revision", 0) + 1
            )
            st.session_state.pop("merge_result", None)
            saved_values = {
                "input_folder": str(input_folder),
                "output_folder": str(output_folder),
            }
            if not config.managed_template_folder:
                saved_values["template_folder"] = str(template_folder)
            save_preferences(saved_values)
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
        st.dataframe(
            _status_table(status_frame),
            key="precheck_status",
            width="stretch",
            height=min(560, max(140, 52 * (len(status_frame) + 1))),
            row_height=52,
            hide_index=True,
            column_config={
                "文件": st.column_config.TextColumn("文件", width="large"),
                "状态": st.column_config.TextColumn("状态", width="medium"),
                "测试类型": st.column_config.TextColumn("测试类型", width="small"),
                "命中字段数": st.column_config.NumberColumn("命中字段数", format="%d", width="small"),
                "缺失字段": st.column_config.TextColumn("缺失字段", width="large"),
                "横轴字段": st.column_config.TextColumn("横轴字段", width="medium"),
                "数据行数": st.column_config.NumberColumn("数据行数", format="%d", width="small"),
                "检查摘要": st.column_config.TextColumn("检查摘要", width="large"),
            },
        )
        with st.expander("模板高亮字段预览"):
            for test_type, template in sorted(precheck.templates.items()):
                st.markdown(f"**{test_type}** — {template.path.name}（第 {template.header_row} 行）")
                st.write("、".join(template.fields))

        st.subheader("3. 合并")
        if precheck.valid_count <= 0:
            st.warning("有效文件数为 0，不能开始合并。")
        else:
            st.caption("可合并文件默认全选；取消勾选后，该文件不会参与本次合并。")
            selected_source_ids = _merge_candidate_table(precheck)
            st.caption(f"已选择 {len(selected_source_ids)} / {precheck.valid_count} 个可合并文件")
        if precheck.valid_count > 0 and st.button(
            "开始合并", type="primary", disabled=not selected_source_ids
        ):
            event_id = str(uuid4())
            started_at = time.monotonic()
            if usage:
                usage.wake()
            progress = st.progress(0.0, text="准备合并")

            def update(done, total, message):
                # File reads have measurable completion counts.  Excel writing
                # has its own sheet-level callbacks and is deliberately capped
                # below 100% until the XLSX writer has really closed the file.
                if message.startswith("excel:"):
                    fraction = done / max(total, 1)
                    value = min(0.95, 0.74 + (0.21 * fraction))
                    label = message.removeprefix("excel:")
                elif message.startswith("正在读取 "):
                    value = 0.05 + (0.65 * (done / max(total, 1)))
                    label = message
                elif message == "正在整理数据并准备生成 Excel":
                    value, label = 0.72, message
                elif message.startswith("Excel 已保存"):
                    value, label = 0.96, message
                elif message == "正在写入处理日志":
                    value, label = 0.98, message
                elif message == "合并完成":
                    value, label = 0.99, "正在确认合并结果"
                else:
                    value, label = 0.02, message
                progress.progress(min(0.99, value), text=label)

            try:
                merged = merge_prechecked(
                    precheck,
                    Path(output_value).expanduser(),
                    config,
                    update,
                    selected_source_ids=selected_source_ids,
                )
                st.session_state["merge_result"] = merged
                duration = time.monotonic() - started_at
                if usage and usage.settings.mode != "off":
                    try:
                        event = create_success_event(event_id, merged, precheck, config, duration)
                        usage.enqueue(event)
                        st.session_state.pop("usage_record_error", None)
                    except Exception:
                        st.session_state["usage_record_error"] = "合并已完成，但本次使用记录未保存。"
                elif usage is None:
                    st.session_state["usage_record_error"] = "合并已完成，但本次使用记录未保存。"
                progress.progress(1.0, text="合并完成")
            except Exception as exc:
                st.error(f"合并失败：{exc}")

    if st.session_state.get("usage_record_error"):
        st.warning(st.session_state["usage_record_error"])
    if usage:
        _usage_status(usage)
    merged = st.session_state.get("merge_result")
    if merged:
        _render_chart(merged, config)


@st.fragment(run_every=5)
def _usage_status(usage):
    try:
        pending, error = usage.outbox.status()
        mode = usage.settings.mode
        if mode == "off":
            st.caption("使用记录：已关闭")
        elif mode == "cache_only":
            st.caption(f"使用记录：仅本地记录 · {pending} 条待同步")
        elif pending:
            st.caption(f"使用记录：待同步 {pending} 条" + (f" · {error}" if error else ""))
        else:
            st.caption("使用记录：已同步")
    except Exception:
        st.caption("使用记录：暂时无法读取同步状态")


main()
