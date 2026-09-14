from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from . import __version__
from .managed_config import (
    ManagedConfigError,
    ManagedSnapshot,
    load_local_operations,
    load_managed_snapshot,
)


class ConfigError(ValueError):
    pass


def project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class AppConfig:
    root: Path
    app: dict[str, Any]
    test_types: dict[str, Any]
    config_version: str = "built-in"
    template_version: str = "built-in"
    config_source: str = "built-in"
    managed_template_folder: Path | None = None
    template_bundle: Path | None = None
    latest_app_version: str = ""
    minimum_app_version: str = ""
    app_download_path: str = ""
    release_note: str = ""
    template_updated: bool = False
    warnings: tuple[str, ...] = ()

    @property
    def type_rules(self) -> dict[str, dict[str, Any]]:
        return self.test_types["test_types"]


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        raise ConfigError(f"无法读取配置 {path.name}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"配置 {path.name} 的顶层必须是映射")
    return data


def _merge_operations(app: dict[str, Any], operations: dict[str, Any]) -> None:
    for section in ("contact", "defaults", "ui", "managed_templates", "support_links", "logging"):
        values = operations.get(section)
        if isinstance(values, dict):
            target = app.setdefault(section, {})
            if isinstance(target, dict):
                target.update(values)
    # Compatibility with releases that used the original Test Data-specific
    # configuration name and field names.
    legacy = operations.get("usage_logging")
    if isinstance(legacy, dict) and "logging" not in operations:
        target = app.setdefault("logging", {})
        target.update({
            "mode": legacy.get("mode", "cache_only"),
            "sharepoint_site_url": legacy.get("site_url", ""),
            "list_name": legacy.get("list_name", ""),
        })


def _version_tuple(value: str) -> tuple[int, int, int]:
    try:
        core = value.split("+", 1)[0].split("-", 1)[0]
        major, minor, patch = core.split(".")
        return int(major), int(minor), int(patch)
    except Exception:
        return 0, 0, 0


def load_config(root: Path | None = None, managed: bool = True) -> AppConfig:
    root = root or project_root()
    config_dir = root / "config"
    app = _read_yaml(config_dir / "app_settings.yaml")
    test_types = _read_yaml(config_dir / "test_types.yaml")
    snapshot: ManagedSnapshot | None = None
    local_operations = load_local_operations() if managed else None
    local_mode = local_operations is not None
    if local_operations is not None:
        _merge_operations(app, local_operations)
    elif managed:
        try:
            snapshot = load_managed_snapshot(app)
        except ManagedConfigError as exc:
            raise ConfigError(str(exc)) from exc
        if snapshot:
            _merge_operations(app, snapshot.operations)
    if not isinstance(test_types.get("test_types"), dict):
        raise ConfigError("test_types.yaml 缺少 test_types")
    from .usage_logging import Settings
    try:
        Settings.from_mapping(app.get("logging", app.get("usage_logging", {})))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ConfigError(f"使用记录配置无效：{exc}") from exc
    colors = app.get("templates", {}).get("selected_fill_rgb", [])
    if not colors:
        raise ConfigError("app_settings.yaml 未配置模板高亮色")
    for name, rule in test_types["test_types"].items():
        for required in ("extensions", "fingerprints", "time_basis", "parser"):
            if required not in rule:
                raise ConfigError(f"测试类型 {name} 缺少配置项 {required}")
    return AppConfig(
        root=root,
        app=app,
        test_types=test_types,
        config_version=(
            snapshot.config_version if snapshot else "local-test" if local_mode else "built-in"
        ),
        template_version=snapshot.template_version if snapshot else "built-in",
        config_source=snapshot.source if snapshot else "local sidecar" if local_mode else "built-in",
        managed_template_folder=snapshot.template_folder if snapshot else None,
        template_bundle=snapshot.template_bundle if snapshot else None,
        latest_app_version=snapshot.latest_app_version if snapshot else __version__,
        minimum_app_version=snapshot.minimum_app_version if snapshot else __version__,
        app_download_path=snapshot.app_download_path if snapshot else "",
        release_note=snapshot.release_note if snapshot else "",
        template_updated=snapshot.template_updated if snapshot else False,
        warnings=tuple(snapshot.warnings) if snapshot else (),
    )


def is_app_update_available(config: AppConfig) -> bool:
    return _version_tuple(config.latest_app_version) > _version_tuple(__version__)


def is_app_update_required(config: AppConfig) -> bool:
    return _version_tuple(config.minimum_app_version) > _version_tuple(__version__)
