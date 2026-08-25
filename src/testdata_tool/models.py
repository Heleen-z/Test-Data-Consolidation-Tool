from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Iterator, Protocol

import pandas as pd


class FileStatus(StrEnum):
    VALID = "有效"
    WARNING = "有警告但可合并"
    INVALID = "无效"
    DUPLICATE = "重复并跳过"


@dataclass(slots=True)
class TemplateDefinition:
    test_type: str
    path: Path
    sheet_name: str
    header_row: int
    fields: list[str]
    selected_colors: list[str] = field(default_factory=list)


@dataclass(slots=True)
class DetectionResult:
    test_type: str | None
    parser_id: str | None
    reason: str
    conflict: bool = False


@dataclass(slots=True)
class HeaderInspection:
    columns: list[str]
    header_row: int
    row_count: int
    delimiter: str | None = None
    encoding: str | None = None


@dataclass(slots=True)
class FileInspection:
    path: Path
    relative_path: str
    source_id: str
    status: FileStatus
    test_type: str | None = None
    parser_id: str | None = None
    messages: list[str] = field(default_factory=list)
    template_path: str = ""
    header_row: int = 0
    columns: list[str] = field(default_factory=list)
    field_map: dict[str, str] = field(default_factory=dict)
    missing_fields: list[str] = field(default_factory=list)
    axis_columns: list[str] = field(default_factory=list)
    row_count: int = 0
    file_size: int = 0
    sha256: str = ""
    delimiter: str | None = None
    encoding: str | None = None
    axis_min: str = ""
    axis_max: str = ""

    @property
    def mergeable(self) -> bool:
        return self.status in (FileStatus.VALID, FileStatus.WARNING)

    def as_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["path"] = str(self.path)
        record["status"] = self.status.value
        record["messages"] = "；".join(self.messages)
        record["matched_fields"] = len(self.field_map)
        record["missing_fields"] = "；".join(self.missing_fields)
        record["axis_columns"] = "；".join(self.axis_columns)
        record.pop("field_map", None)
        record.pop("columns", None)
        return record


@dataclass(slots=True)
class PrecheckResult:
    input_folder: Path
    template_folder: Path
    templates: dict[str, TemplateDefinition]
    files: list[FileInspection]
    scanned_count: int

    @property
    def valid_count(self) -> int:
        return sum(item.mergeable for item in self.files)

    def dataframe(self) -> pd.DataFrame:
        return pd.DataFrame([item.as_record() for item in self.files])


@dataclass(slots=True)
class MergeResult:
    output_path: Path
    validation_path: Path
    log_path: Path
    dataset_folder: Path
    datasets: dict[str, Path]
    type_rows: dict[str, int]
    source_index: pd.DataFrame
    validation: pd.DataFrame


class Parser(Protocol):
    parser_id: str

    def probe(self, path: Path) -> bool: ...

    def inspect(
        self, path: Path, expected_fields: list[str], axis_candidates: list[str]
    ) -> HeaderInspection: ...

    def iter_batches(
        self, path: Path, inspection: FileInspection, chunk_rows: int
    ) -> Iterator[pd.DataFrame]: ...
