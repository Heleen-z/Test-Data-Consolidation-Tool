from __future__ import annotations

import sys
from pathlib import Path

from .config import AppConfig
from .preferences import load_preferences


def executable_folder() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def default_template_folder(config: AppConfig) -> Path:
    if config.managed_template_folder and config.managed_template_folder.is_dir():
        return config.managed_template_folder
    configured = config.app.get("defaults", {}).get("template_folder", "")
    if configured:
        path = Path(configured).expanduser()
        if not path.is_absolute():
            path = config.root / path
        if path.is_dir():
            return path
    preferences = load_preferences()
    candidates = [
        preferences.get("template_folder", ""),
        str(config.root / "template"),
    ]
    configured_library = config.app.get("defaults", {}).get("default_template_library", "")
    if configured_library:
        candidates.insert(1, configured_library)
    for value in candidates:
        if value and Path(value).is_dir():
            return Path(value)
    return config.root / "template"
