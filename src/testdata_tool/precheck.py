from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .axis import axis_bounds, build_axis, find_axis_columns
from .config import AppConfig
from .models import (
    DetectionResult,
    FileInspection,
    FileStatus,
    HeaderInspection,
    PrecheckResult,
    TemplateDefinition,
)
from .normalize import match_headers, normalize_header
from .parsers import ParserRegistry
from .recognition import detect_type
from .templates import load_templates


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _is_within(path: Path, folder: Path | None) -> bool:
    if not folder:
        return False
    try:
        path.resolve().relative_to(folder.resolve())
        return True
    except ValueError:
        return False


def _aliases(config: AppConfig, test_type: str) -> dict[str, list[str]]:
    raw = config.app.get("matching", {}).get("aliases", {}) or {}
    if test_type in raw and isinstance(raw[test_type], dict):
        return raw[test_type]
    return {key: value for key, value in raw.items() if isinstance(value, list)}


def _candidate_files(
    input_folder: Path,
    template_folder: Path,
    output_folder: Path | None,
    config: AppConfig,
) -> list[Path]:
    extensions = {
        str(ext).casefold()
        for rule in config.type_rules.values()
        for ext in rule.get("extensions", [])
    } | {".csv", ".txt", ".xlsx", ".xlsm"}
    patterns = [normalize_header(item) for item in config.test_types.get("template_like_patterns", [])]
    candidates: list[Path] = []
    for path in input_folder.rglob("*"):
        if not path.is_file() or path.suffix.casefold() not in extensions:
            continue
        if _is_within(path, template_folder) or _is_within(path, output_folder):
            continue
        if any(pattern in normalize_header(path.name) for pattern in patterns):
            continue
        candidates.append(path)
    return sorted(candidates, key=lambda item: str(item).casefold())


def _infer_from_templates(
    path: Path,
    templates: dict[str, TemplateDefinition],
    config: AppConfig,
    registry: ParserRegistry,
) -> tuple[DetectionResult, HeaderInspection | None]:
    scored: list[tuple[int, str, str, HeaderInspection]] = []
    for test_type, template in templates.items():
        rule = config.type_rules.get(test_type, {})
        parser_id = rule.get("parser")
        parser = registry.get(parser_id)
        if not parser.probe(path):
            continue
        try:
            header = parser.inspect(path, template.fields, rule.get("axis_candidates", []))
        except Exception:
            continue
        mapping, errors = match_headers(template.fields, header.columns, _aliases(config, test_type))
        axes = find_axis_columns(header.columns, rule)
        score = len(mapping) * 10 + len(axes) * 3 - len(errors) * 100
        if score > 0:
            scored.append((score, test_type, parser_id, header))
    if not scored:
        return DetectionResult(None, None, "表头未匹配任何模板"), None
    scored.sort(key=lambda item: item[0], reverse=True)
    winners = [item for item in scored if item[0] == scored[0][0]]
    if len(winners) != 1:
        return (
            DetectionResult(
                None,
                None,
                "表头类型冲突：" + "、".join(item[1] for item in winners),
                conflict=True,
            ),
            None,
        )
    _, test_type, parser_id, header = winners[0]
    return DetectionResult(test_type, parser_id, "模板字段匹配"), header


def run_precheck(
    input_folder: Path,
    template_folder: Path,
    output_folder: Path | None,
    config: AppConfig,
) -> PrecheckResult:
    if not input_folder.is_dir():
        raise ValueError(f"输入目录不存在：{input_folder}")
    templates = load_templates(template_folder, config)
    registry = ParserRegistry()
    candidates = _candidate_files(input_folder, template_folder, output_folder, config)
    files: list[FileInspection] = []
    known_hashes: dict[str, str] = {}
    max_bytes = int(config.app.get("scan", {}).get("max_file_mb", 2048)) * 1024 * 1024

    for index, path in enumerate(candidates, 1):
        relative = str(path.relative_to(input_folder))
        source_id = f"SRC-{index:06d}"
        item = FileInspection(
            path=path,
            relative_path=relative,
            source_id=source_id,
            status=FileStatus.INVALID,
            file_size=path.stat().st_size,
        )
        files.append(item)
        if item.file_size == 0:
            item.messages.append("文件为空")
            continue
        if item.file_size > max_bytes:
            item.messages.append("文件超过允许大小")
            continue
        try:
            item.sha256 = sha256_file(path)
        except OSError as exc:
            item.messages.append(f"无法读取文件：{exc}")
            continue
        if item.sha256 in known_hashes:
            item.status = FileStatus.DUPLICATE
            item.messages.append(f"与 {known_hashes[item.sha256]} 完全重复")
            continue
        known_hashes[item.sha256] = relative

        detection = detect_type(path, config)
        cached_header: HeaderInspection | None = None
        if detection.test_type is None or detection.conflict:
            detection, cached_header = _infer_from_templates(
                path, templates, config, registry
            )
        if not detection.test_type:
            item.messages.append(detection.reason)
            continue
        item.test_type = detection.test_type
        item.parser_id = detection.parser_id
        template = templates.get(item.test_type)
        if not template:
            item.messages.append(f"没有找到 {item.test_type} 对应的模板")
            continue
        item.template_path = str(template.path)
        parser = registry.get(item.parser_id)
        if not parser.probe(path):
            item.messages.append(
                f"{item.test_type} 的 {path.suffix} 专用解析属于第二阶段，当前不可合并"
            )
            continue
        rule = config.type_rules[item.test_type]
        try:
            header = cached_header or parser.inspect(
                path, template.fields, rule.get("axis_candidates", [])
            )
        except Exception as exc:
            item.messages.append(f"无法解析表头：{exc}")
            continue
        item.header_row = header.header_row
        item.columns = header.columns
        item.row_count = header.row_count
        item.delimiter = header.delimiter
        item.encoding = header.encoding
        if item.row_count <= 0:
            item.messages.append("没有数据行")
            continue
        item.field_map, match_errors = match_headers(
            template.fields, item.columns, _aliases(config, item.test_type)
        )
        if match_errors:
            item.messages.extend(match_errors)
            continue
        if not item.field_map:
            item.messages.append("没有匹配到任何黄色或绿色模板字段")
            continue
        item.missing_fields = [
            field for field in template.fields if field not in item.field_map
        ]
        item.axis_columns = find_axis_columns(item.columns, rule)
        if not item.axis_columns:
            item.messages.append("缺少可识别的横轴（时间、循环或频率）")
            continue
        try:
            sample = next(parser.iter_batches(path, item, min(1000, item.row_count)))
            axis = build_axis(sample, rule.get("time_basis", "unknown"), item.axis_columns)
            if axis.notna().sum() == 0:
                item.messages.append("横轴字段存在，但样本值无法解析")
                continue
            item.axis_min, item.axis_max = axis_bounds(axis)
        except Exception as exc:
            item.messages.append(f"样本数据无法读取：{exc}")
            continue
        if item.missing_fields:
            item.status = FileStatus.WARNING
            item.messages.append(f"缺少 {len(item.missing_fields)} 个模板字段，将补空")
        else:
            item.status = FileStatus.VALID

    return PrecheckResult(
        input_folder=input_folder,
        template_folder=template_folder,
        templates=templates,
        files=files,
        scanned_count=len(candidates),
    )
