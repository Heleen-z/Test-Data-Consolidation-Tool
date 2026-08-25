from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


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


def load_config(root: Path | None = None) -> AppConfig:
    root = root or project_root()
    config_dir = root / "config"
    app = _read_yaml(config_dir / "app_settings.yaml")
    test_types = _read_yaml(config_dir / "test_types.yaml")
    if not isinstance(test_types.get("test_types"), dict):
        raise ConfigError("test_types.yaml 缺少 test_types")
    colors = app.get("templates", {}).get("selected_fill_rgb", [])
    if not colors:
        raise ConfigError("app_settings.yaml 未配置模板高亮色")
    for name, rule in test_types["test_types"].items():
        for required in ("extensions", "fingerprints", "time_basis", "parser"):
            if required not in rule:
                raise ConfigError(f"测试类型 {name} 缺少配置项 {required}")
    return AppConfig(root=root, app=app, test_types=test_types)

