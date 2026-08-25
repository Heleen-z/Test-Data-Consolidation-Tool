from __future__ import annotations

import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd

from .axis import build_axis
from .config import AppConfig
from .export import export_workbook
from .models import FileInspection, MergeResult, PrecheckResult
from .normalize import normalize_header
from .parsers import ParserRegistry


HELPER_COLUMNS = ["__axis_value", "__source_id", "__source_row", "__sort_order"]


def _safe_numeric(series: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(series):
        return series
    converted = pd.to_numeric(series, errors="coerce")
    non_empty = series.notna() & series.astype(str).str.strip().ne("")
    if non_empty.sum() and converted[non_empty].notna().mean() >= 0.95:
        return converted
    return series


def _transform_batch(
    frame: pd.DataFrame,
    item: FileInspection,
    template_fields: list[str],
    rule: dict,
    sort_start: int,
) -> pd.DataFrame:
    frame = frame.dropna(how="all").copy()
    if frame.empty:
        return frame
    frame.columns = [str(column).strip() for column in frame.columns]
    axis = build_axis(frame, rule.get("time_basis", "unknown"), item.axis_columns)
    valid_axis = axis.notna()
    frame = frame.loc[valid_axis].copy()
    axis = axis.loc[valid_axis]
    if frame.empty:
        return frame

    output = pd.DataFrame(index=frame.index)
    axis_output = list(rule.get("axis_output", []))
    for position, actual in enumerate(item.axis_columns):
        output_name = axis_output[position] if position < len(axis_output) else actual
        output[output_name] = frame[actual]

    axis_keys = {normalize_header(name) for name in output.columns}
    for canonical in template_fields:
        if normalize_header(canonical) in axis_keys:
            continue
        actual = item.field_map.get(canonical)
        output[canonical] = frame[actual] if actual in frame.columns else pd.NA
        output[canonical] = _safe_numeric(output[canonical])

    output["__axis_value"] = axis.to_numpy()
    output["__source_id"] = item.source_id
    output["__source_row"] = frame.index.to_series().astype("int64").to_numpy() + item.header_row + 2
    output["__sort_order"] = range(sort_start, sort_start + len(output))
    return output.reset_index(drop=True)


def _sort_type(frame: pd.DataFrame, time_basis: str) -> pd.DataFrame:
    if frame.empty:
        return frame
    if time_basis == "absolute":
        keys = ["__axis_value", "__sort_order", "__source_row"]
    else:
        keys = ["__source_id", "__axis_value", "__source_row"]
    return frame.sort_values(keys, kind="stable", na_position="last").reset_index(drop=True)


def _unique_output_path(output_folder: Path, configured_name: str) -> Path:
    output_folder.mkdir(parents=True, exist_ok=True)
    candidate = output_folder / configured_name
    if not candidate.exists():
        return candidate
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return output_folder / f"{candidate.stem}_{stamp}{candidate.suffix}"


def merge_prechecked(
    precheck: PrecheckResult,
    output_folder: Path,
    config: AppConfig,
    progress_callback=None,
) -> MergeResult:
    mergeable = [item for item in precheck.files if item.mergeable]
    if not mergeable:
        raise ValueError("没有可合并的有效文件，请先完成 Pre-check")
    chunk_rows = int(config.app.get("merge", {}).get("chunk_rows", 200_000))
    registry = ParserRegistry()
    frames_by_type: dict[str, list[pd.DataFrame]] = defaultdict(list)
    source_rows: list[dict] = []
    total = len(mergeable)
    sort_counter = 0

    for position, item in enumerate(mergeable, 1):
        if progress_callback:
            progress_callback(position - 1, total, f"正在读取 {item.relative_path}")
        parser = registry.get(item.parser_id)
        template = precheck.templates[item.test_type]
        rule = config.type_rules[item.test_type]
        merged_rows = 0
        file_frames: list[pd.DataFrame] = []
        try:
            for batch in parser.iter_batches(item.path, item, chunk_rows):
                transformed = _transform_batch(
                    batch,
                    item,
                    template.fields,
                    rule,
                    sort_counter,
                )
                if transformed.empty:
                    continue
                file_frames.append(transformed)
                merged_rows += len(transformed)
                sort_counter += len(transformed)
            frames_by_type[item.test_type].extend(file_frames)
            status = item.status.value
            warning = "；".join(item.messages)
        except Exception as exc:
            merged_rows = 0
            status = "合并失败"
            warning = "；".join([*item.messages, str(exc)])
        source_rows.append(
            {
                "Source_ID": item.source_id,
                "测试类型": item.test_type,
                "相对路径": item.relative_path,
                "文件名": item.path.name,
                "文件大小": item.file_size,
                "SHA256": item.sha256,
                "原始记录数": item.row_count,
                "合并记录数": merged_rows,
                "解析器": item.parser_id,
                "状态": status,
                "警告摘要": warning,
                "最小时间或循环": item.axis_min,
                "最大时间或循环": item.axis_max,
            }
        )

    dataset_folder = Path(tempfile.mkdtemp(prefix="testdata_tool_"))
    datasets: dict[str, Path] = {}
    type_rows: dict[str, int] = {}
    for test_type, frames in frames_by_type.items():
        if not frames:
            continue
        combined = pd.concat(frames, ignore_index=True, sort=False)
        for column in combined.columns:
            if not column.startswith("__"):
                combined[column] = _safe_numeric(combined[column])
        combined = _sort_type(combined, config.type_rules[test_type].get("time_basis", "unknown"))
        dataset_path = dataset_folder / f"{test_type}.parquet"
        combined.to_parquet(dataset_path, index=False)
        datasets[test_type] = dataset_path
        type_rows[test_type] = len(combined)
    if not datasets:
        raise ValueError("所有文件都在合并阶段失败，请查看验证信息")

    source_index = pd.DataFrame(source_rows)
    validation = precheck.dataframe()
    configured_name = config.app.get("export", {}).get("merged_name", "Merged Dataset.xlsx")
    output_path = _unique_output_path(output_folder, configured_name)
    if progress_callback:
        progress_callback(total, total, "正在生成 Excel 工作簿")
    export_workbook(
        output_path,
        datasets,
        source_index,
        validation,
        precheck,
        config,
    )
    validation_name = config.app.get("export", {}).get(
        "validation_name", "Validation Report.xlsx"
    )
    validation_path = _unique_output_path(output_folder, validation_name)
    validation.to_excel(validation_path, index=False, engine="openpyxl")
    log_name = config.app.get("export", {}).get("log_name", "Processing Log.txt")
    log_path = output_folder / log_name
    log_lines = [
        f"Testing Data Consolidation Tool {datetime.now():%Y-%m-%d %H:%M:%S}",
        f"Input: {precheck.input_folder}",
        f"Templates: {precheck.template_folder}",
        f"Output: {output_path}",
        f"Scanned: {precheck.scanned_count}",
        f"Mergeable: {precheck.valid_count}",
        "",
    ]
    for row in source_rows:
        log_lines.append(
            f"[{row['状态']}] {row['测试类型']} {row['相对路径']} "
            f"rows={row['合并记录数']} {row['警告摘要']}"
        )
    log_path.write_text("\n".join(log_lines), encoding="utf-8")
    if progress_callback:
        progress_callback(total, total, "合并完成")
    return MergeResult(
        output_path=output_path,
        validation_path=validation_path,
        log_path=log_path,
        dataset_folder=dataset_folder,
        datasets=datasets,
        type_rows=type_rows,
        source_index=source_index,
        validation=validation,
    )
