from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import threading
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

import yaml
from openpyxl import load_workbook


class ManagedConfigError(ValueError):
    pass


LOCAL_CONFIG_FILENAME = "local-config.yaml"


@dataclass(frozen=True)
class ManagedSnapshot:
    operations: dict[str, Any]
    config_version: str
    template_version: str
    template_folder: Path
    template_bundle: Path
    source: str
    published_at: str = ""
    published_by: str = ""
    latest_app_version: str = ""
    minimum_app_version: str = ""
    app_download_path: str = ""
    release_note: str = ""
    template_updated: bool = False
    warnings: list[str] = field(default_factory=list)


def executable_folder() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def local_config_path() -> Path:
    """Return the optional test-only configuration placed next to the EXE."""
    return executable_folder() / LOCAL_CONFIG_FILENAME


def managed_cache_root() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return base / "FORVIA" / "TestDataConsolidation" / "managed"


def _read_mapping(path: Path) -> dict[str, Any]:
    try:
        if path.suffix.lower() == ".json":
            value = json.loads(path.read_text(encoding="utf-8"))
        else:
            value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        raise ManagedConfigError(f"无法读取 {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ManagedConfigError(f"{path.name} 顶层必须是映射")
    return value


def discover_central_root(packaged_app: dict[str, Any]) -> Path | None:
    value = os.environ.get("TESTDATA_TOOL_CONFIG_ROOT", "").strip()
    sidecar = executable_folder() / "bootstrap.yaml"
    if not value and sidecar.is_file():
        value = str(_read_mapping(sidecar).get("central_root", "")).strip()
    if not value and getattr(sys, "frozen", False):
        value = str(
            packaged_app.get("central_management", {}).get("central_root", "")
        ).strip()
    if not value:
        return None
    root = Path(value).expanduser()
    if not root.is_absolute():
        raise ManagedConfigError("中央配置根目录必须使用绝对路径或 UNC 路径")
    return root


def _relative_path(root: Path, value: Any, label: str) -> Path:
    raw = str(value or "").replace("\\", "/")
    pure = PurePosixPath(raw)
    if not raw or pure.is_absolute() or ".." in pure.parts or pure.drive:
        raise ManagedConfigError(f"{label} 必须是中央根目录内的安全相对路径")
    return root.joinpath(*pure.parts)


def _require_mapping(parent: dict[str, Any], key: str) -> dict[str, Any]:
    value = parent.get(key)
    if not isinstance(value, dict):
        raise ManagedConfigError(f"发布清单缺少对象：{key}")
    return value


def _validate_version(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", text):
        raise ManagedConfigError(f"{label} 版本格式无效：{text or '(空)'}")
    return text


def _validate_manifest(data: dict[str, Any], root: Path) -> dict[str, Any]:
    if data.get("schema_version") != 1:
        raise ManagedConfigError("仅支持 release-manifest schema_version: 1")
    config = _require_mapping(data, "config")
    templates = _require_mapping(data, "templates")
    application = _require_mapping(data, "application")
    _validate_version(config.get("version"), "配置")
    _validate_version(templates.get("version"), "模板")
    _validate_version(application.get("latest_version"), "最新程序")
    _validate_version(application.get("minimum_supported_version"), "最低程序")
    for item, label in ((config, "配置"), (templates, "模板")):
        _relative_path(root, item.get("path"), f"{label}路径")
        if not re.fullmatch(r"[0-9A-Fa-f]{64}", str(item.get("sha256", ""))):
            raise ManagedConfigError(f"{label} SHA256 无效")
    _relative_path(root, application.get("download_path"), "程序下载路径")
    return data


_ALLOWED_OPERATION_KEYS = {
    "logging",
    "usage_logging",
    "schema_version",
    "contact",
    "defaults",
    "ui",
    "managed_templates",
    "support_links",
}
_ALLOWED_SECTION_KEYS = {
    "logging": {"mode", "sharepoint_site_url", "list_name", "tool_name", "excel_bridge_enabled", "seed_url"},
    "usage_logging": {"mode", "site_url", "list_name"},
    "contact": {"owner", "email", "phone", "note"},
    "defaults": {"input_folder", "output_folder"},
    "ui": {"brand_title", "announcement", "help_text"},
    "managed_templates": {
        "required",
        "download_label",
        "update_message",
        "success_message",
    },
    "support_links": {"user_guide", "issue_form"},
}


def _validate_operations(data: dict[str, Any]) -> dict[str, Any]:
    if data.get("schema_version") != 1:
        raise ManagedConfigError("仅支持 operations schema_version: 1")
    unknown = set(data) - _ALLOWED_OPERATION_KEYS
    if unknown:
        raise ManagedConfigError(f"运营配置包含不允许的项目：{', '.join(sorted(unknown))}")
    if "logging" in data and "usage_logging" in data:
        raise ManagedConfigError("运营配置不能同时包含 logging 和 usage_logging")
    for section, allowed in _ALLOWED_SECTION_KEYS.items():
        value = data.get(section, {})
        if not isinstance(value, dict):
            raise ManagedConfigError(f"运营配置 {section} 必须是映射")
        extra = set(value) - allowed
        if extra:
            raise ManagedConfigError(
                f"运营配置 {section} 包含不允许的项目：{', '.join(sorted(extra))}"
            )
    email = str(data.get("contact", {}).get("email", "")).strip()
    if email and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise ManagedConfigError(f"支持邮箱格式无效：{email}")
    required = data.get("managed_templates", {}).get("required", True)
    if not isinstance(required, bool):
        raise ManagedConfigError("managed_templates.required 必须是 true 或 false")
    for section, values in data.items():
        if section in ("schema_version", "managed_templates"):
            continue
        if isinstance(values, dict):
            invalid = [key for key, value in values.items()
                       if not isinstance(value, str)
                       and not (section == "logging" and key == "excel_bridge_enabled" and isinstance(value, bool))]
            if invalid:
                raise ManagedConfigError(
                    f"运营配置 {section} 的字段必须是文本：{', '.join(invalid)}"
                )
    template_values = data.get("managed_templates", {})
    invalid_templates = [
        key
        for key, value in template_values.items()
        if key != "required" and not isinstance(value, str)
    ]
    if invalid_templates:
        raise ManagedConfigError(
            "运营配置 managed_templates 的提示字段必须是文本："
            + ", ".join(invalid_templates)
        )
    from .usage_logging import Settings
    try:
        Settings.from_mapping(data.get("logging", data.get("usage_logging", {})))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ManagedConfigError(f"使用记录配置无效：{exc}") from exc
    return data


def _validate_local_operations(data: dict[str, Any]) -> dict[str, Any]:
    """Validate a local sidecar without granting it central-release privileges."""
    defaults = data.get("defaults", {})
    if not isinstance(defaults, dict):
        raise ManagedConfigError("本地配置 defaults 必须是映射")
    template_folder = defaults.get("template_folder")
    if template_folder is not None and not isinstance(template_folder, str):
        raise ManagedConfigError("本地配置 defaults.template_folder 必须是文本路径")
    # Central operations intentionally cannot set a template directory.  A local
    # test sidecar may do so, but all other keys retain the same strict schema.
    validation_data = dict(data)
    validation_defaults = dict(defaults)
    validation_defaults.pop("template_folder", None)
    validation_data["defaults"] = validation_defaults
    _validate_operations(validation_data)
    return data


def load_local_operations(path: Path | None = None) -> dict[str, Any] | None:
    """Load an explicit local test override, if an EXE-sidecar is present."""
    sidecar = path or local_config_path()
    if not sidecar.is_file():
        return None
    try:
        return _validate_local_operations(_read_mapping(sidecar))
    except ManagedConfigError as exc:
        raise ManagedConfigError(f"本地测试配置 {sidecar.name} 无效：{exc}") from exc


def _read_manifest_with_timeout(path: Path, seconds: float) -> dict[str, Any]:
    result: list[dict[str, Any]] = []
    errors: list[Exception] = []

    def read() -> None:
        try:
            result.append(_read_mapping(path))
        except Exception as exc:
            errors.append(exc)

    worker = threading.Thread(target=read, name="central-config-read", daemon=True)
    worker.start()
    worker.join(seconds)
    if worker.is_alive():
        raise ManagedConfigError(f"读取中央发布清单超过 {seconds:g} 秒")
    if errors:
        raise errors[0]
    return result[0]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _copy_verified(source: Path, target: Path, expected: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file():
        if _sha256(target) == expected.upper():
            return
        raise ManagedConfigError(f"版本目录中的 {target.name} 已存在但内容不同")
    temporary = target.with_name(f"{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        shutil.copyfile(source, temporary)
        if _sha256(temporary) != expected.upper():
            raise ManagedConfigError(f"{source.name} 的 SHA256 校验失败")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def _extract_template_bundle(bundle: Path, destination: Path) -> Path:
    extract_root = destination / "templates"
    extract_root.mkdir(parents=True, exist_ok=False)
    try:
        with zipfile.ZipFile(bundle) as archive:
            for member in archive.infolist():
                pure = PurePosixPath(member.filename.replace("\\", "/"))
                if pure.is_absolute() or ".." in pure.parts or pure.drive:
                    raise ManagedConfigError(f"模板包包含不安全路径：{member.filename}")
            archive.extractall(extract_root)
    except ManagedConfigError:
        raise
    except Exception as exc:
        raise ManagedConfigError(f"模板包无法解压：{exc}") from exc
    candidates = [extract_root, *[p for p in extract_root.iterdir() if p.is_dir()]]
    template_folder = next((p for p in candidates if list(p.glob("*.xlsx"))), None)
    if template_folder is None:
        raise ManagedConfigError("模板包中没有找到 xlsx 模板")
    for workbook_path in template_folder.glob("*.xlsx"):
        try:
            workbook = load_workbook(
                workbook_path, read_only=True, data_only=True, keep_links=False
            )
            workbook.close()
        except Exception as exc:
            raise ManagedConfigError(
                f"模板文件无法读取 {workbook_path.name}: {exc}"
            ) from exc
    return template_folder


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


def _activate_from_central(
    root: Path, cache: Path, manifest_data: dict[str, Any]
) -> ManagedSnapshot:
    manifest = _validate_manifest(manifest_data, root)
    config_spec = manifest["config"]
    template_spec = manifest["templates"]
    application = manifest["application"]
    config_version = str(config_spec["version"])
    template_version = str(template_spec["version"])

    config_target = cache / "config" / config_version / "operations.yaml"
    _copy_verified(
        _relative_path(root, config_spec["path"], "配置路径"),
        config_target,
        str(config_spec["sha256"]),
    )
    operations = _validate_operations(_read_mapping(config_target))

    version_root = cache / "templates" / template_version
    template_updated = not version_root.is_dir()
    if template_updated:
        staging = cache / "staging" / f"templates-{uuid.uuid4().hex}"
        staging.mkdir(parents=True, exist_ok=False)
        try:
            bundle = staging / "TemplateBundle.zip"
            _copy_verified(
                _relative_path(root, template_spec["path"], "模板路径"),
                bundle,
                str(template_spec["sha256"]),
            )
            relative_folder = _extract_template_bundle(bundle, staging).relative_to(staging)
            version_root.parent.mkdir(parents=True, exist_ok=True)
            staging.replace(version_root)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
    else:
        folders = [version_root / "templates", *version_root.glob("templates/*")]
        relative_folder = next(
            (p.relative_to(version_root) for p in folders if p.is_dir() and list(p.glob("*.xlsx"))),
            None,
        )
        if relative_folder is None:
            raise ManagedConfigError("本机模板缓存不完整")

    cached_application = dict(application)
    cached_application["download_path"] = str(
        _relative_path(root, application["download_path"], "程序下载路径")
    )
    active = {
        "schema_version": 1,
        "config_version": config_version,
        "template_version": template_version,
        "template_relative_folder": relative_folder.as_posix(),
        "published_at": str(manifest.get("published_at", "")),
        "published_by": str(manifest.get("published_by", "")),
        "application": cached_application,
    }
    _write_json_atomic(cache / "active.json", active)
    return ManagedSnapshot(
        operations=operations,
        config_version=config_version,
        template_version=template_version,
        template_folder=version_root / relative_folder,
        template_bundle=version_root / "TemplateBundle.zip",
        source="central",
        published_at=active["published_at"],
        published_by=active["published_by"],
        latest_app_version=str(application["latest_version"]),
        minimum_app_version=str(application["minimum_supported_version"]),
        app_download_path=str(_relative_path(root, application["download_path"], "程序下载路径")),
        release_note=str(application.get("release_note", "")),
        template_updated=template_updated,
    )


def _load_last_known_good(cache: Path, warning: str) -> ManagedSnapshot:
    active = _read_mapping(cache / "active.json")
    config_version = str(active["config_version"])
    template_version = str(active["template_version"])
    operations = _validate_operations(
        _read_mapping(cache / "config" / config_version / "operations.yaml")
    )
    version_root = cache / "templates" / template_version
    template_folder = version_root / str(active["template_relative_folder"])
    if not template_folder.is_dir():
        raise ManagedConfigError("last-known-good 模板缓存不存在")
    application = active.get("application", {})
    return ManagedSnapshot(
        operations=operations,
        config_version=config_version,
        template_version=template_version,
        template_folder=template_folder,
        template_bundle=version_root / "TemplateBundle.zip",
        source="cache",
        published_at=str(active.get("published_at", "")),
        published_by=str(active.get("published_by", "")),
        latest_app_version=str(application.get("latest_version", "")),
        minimum_app_version=str(application.get("minimum_supported_version", "")),
        app_download_path=str(application.get("download_path", "")),
        release_note=str(application.get("release_note", "")),
        warnings=[warning],
    )


def load_managed_snapshot(packaged_app: dict[str, Any]) -> ManagedSnapshot | None:
    root = discover_central_root(packaged_app)
    if root is None:
        return None
    cache = managed_cache_root()
    timeout = float(
        packaged_app.get("central_management", {}).get("startup_timeout_seconds", 5)
    )
    timeout = min(30.0, max(1.0, timeout))
    try:
        manifest = _read_manifest_with_timeout(root / "release-manifest.json", timeout)
        return _activate_from_central(root, cache, manifest)
    except Exception as exc:
        try:
            return _load_last_known_good(
                cache, f"中央配置暂不可用，正在使用上次有效版本：{exc}"
            )
        except Exception as cache_exc:
            raise ManagedConfigError(
                f"中央配置不可用，并且本机没有有效缓存。中央错误：{exc}；缓存错误：{cache_exc}"
            ) from exc
