from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import __version__
from .config import AppConfig
from .models import FileStatus, PrecheckResult


INVALID_SHEET_CHARS = re.compile(r"[\[\]:*?/\\]")


def safe_sheet_name(name: str, existing: set[str] | None = None) -> str:
    existing = existing if existing is not None else set()
    base = INVALID_SHEET_CHARS.sub("_", str(name)).strip(" '")[:31] or "Data"
    candidate = base
    number = 2
    while candidate.casefold() in {item.casefold() for item in existing}:
        suffix = f"_{number}"
        candidate = base[: 31 - len(suffix)] + suffix
        number += 1
    existing.add(candidate)
    return candidate


def _format_sheet(writer, sheet_name: str, frame: pd.DataFrame, hidden: list[str] | None = None):
    worksheet = writer.sheets[sheet_name]
    worksheet.freeze_panes(1, 0)
    if len(frame.columns):
        worksheet.autofilter(0, 0, max(0, len(frame)), len(frame.columns) - 1)
    for index, column in enumerate(frame.columns):
        width = min(42, max(12, len(str(column)) + 2))
        options = {"hidden": True} if hidden and column in hidden else None
        worksheet.set_column(index, index, width, None, options)


def _summary_frames(
    precheck: PrecheckResult, datasets: dict[str, Path], config: AppConfig
) -> tuple[pd.DataFrame, pd.DataFrame]:
    statuses = {status.value: 0 for status in FileStatus}
    for item in precheck.files:
        statuses[item.status.value] += 1
    overview = pd.DataFrame(
        [
            ("程序版本", __version__),
            ("处理时间", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            ("输入目录", str(precheck.input_folder)),
            ("模板目录", str(precheck.template_folder)),
            ("扫描文件数", precheck.scanned_count),
            ("有效文件数", statuses[FileStatus.VALID.value]),
            ("警告但可合并", statuses[FileStatus.WARNING.value]),
            ("无效文件数", statuses[FileStatus.INVALID.value]),
            ("重复文件数", statuses[FileStatus.DUPLICATE.value]),
        ],
        columns=["项目", "值"],
    )
    details: list[dict] = []
    for test_type, path in datasets.items():
        frame = pd.read_parquet(path)
        visible = [column for column in frame.columns if not column.startswith("__")]
        details.append(
            {
                "测试类型": test_type,
                "文件数": sum(
                    item.mergeable and item.test_type == test_type for item in precheck.files
                ),
                "记录数": len(frame),
                "可见列数": len(visible),
                "模板": precheck.templates[test_type].path.name,
            }
        )
    return overview, pd.DataFrame(details)


def export_workbook(
    output_path: Path,
    datasets: dict[str, Path],
    source_index: pd.DataFrame,
    validation: pd.DataFrame,
    precheck: PrecheckResult,
    config: AppConfig,
) -> None:
    max_rows = min(
        1_048_575,
        int(config.app.get("export", {}).get("visible_excel_rows", 1_048_575)),
    )
    existing: set[str] = set()
    overview, type_summary = _summary_frames(precheck, datasets, config)
    with pd.ExcelWriter(
        output_path,
        engine="xlsxwriter",
        datetime_format="yyyy-mm-dd hh:mm:ss.000",
        engine_kwargs={"options": {"strings_to_urls": False, "nan_inf_to_errors": True}},
    ) as writer:
        summary_name = safe_sheet_name("Summary", existing)
        overview.to_excel(writer, sheet_name=summary_name, index=False, startrow=0)
        type_start = len(overview) + 3
        type_summary.to_excel(writer, sheet_name=summary_name, index=False, startrow=type_start)
        summary_sheet = writer.sheets[summary_name]
        summary_sheet.freeze_panes(1, 0)
        summary_sheet.set_column(0, 0, 22)
        summary_sheet.set_column(1, 5, 46)

        for test_type, dataset_path in datasets.items():
            frame = pd.read_parquet(dataset_path)
            parts = max(1, (len(frame) + max_rows - 1) // max_rows)
            for part in range(parts):
                start = part * max_rows
                segment = frame.iloc[start : start + max_rows]
                desired = test_type if parts == 1 else f"{test_type}_{part + 1}"
                sheet_name = safe_sheet_name(desired, existing)
                segment.to_excel(writer, sheet_name=sheet_name, index=False)
                _format_sheet(
                    writer,
                    sheet_name,
                    segment,
                    hidden=[column for column in segment.columns if column.startswith("__")],
                )

        source_name = safe_sheet_name("Source_Index", existing)
        source_index.to_excel(writer, sheet_name=source_name, index=False)
        _format_sheet(writer, source_name, source_index)

        validation_name = safe_sheet_name("Validation", existing)
        validation.to_excel(writer, sheet_name=validation_name, index=False)
        _format_sheet(writer, validation_name, validation)

