"""Read the portable release's remote version information without changing it."""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


_VERSION = re.compile(r"^\d+\.\d+\.\d+$")


@dataclass(frozen=True)
class VersionCheckResult:
    state: str
    message: str
    local_version: str
    latest_version: str = ""
    minimum_supported_version: str = ""
    release_note: str = ""
    download_folder: str = ""

    @property
    def update_available(self) -> bool:
        return self.state == "update_available"

    @property
    def update_required(self) -> bool:
        return self.state == "update_required"


def version_tuple(value: str) -> tuple[int, int, int]:
    if not _VERSION.fullmatch(value):
        raise ValueError(f"版本号必须为 主版本.次版本.修订号：{value or '(空)'}")
    return tuple(int(part) for part in value.split("."))  # type: ignore[return-value]


def _mapping_from_yaml(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        raise ValueError(f"无法读取云端配置：{exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("云端配置顶层必须是映射")
    return value


def _read_with_timeout(path: Path, timeout_seconds: float) -> dict[str, Any]:
    result: list[dict[str, Any]] = []
    errors: list[Exception] = []

    def read() -> None:
        try:
            result.append(_mapping_from_yaml(path))
        except Exception as exc:
            errors.append(exc)

    worker = threading.Thread(target=read, name="remote-version-check", daemon=True)
    worker.start()
    worker.join(timeout_seconds)
    if worker.is_alive():
        raise ValueError(f"读取云端版本配置超过 {timeout_seconds:g} 秒")
    if errors:
        raise errors[0]
    return result[0]


def check_remote_version(app: dict[str, Any], local_version: str) -> VersionCheckResult:
    """Compare this executable version to the release information in a remote YAML file."""
    try:
        local = version_tuple(local_version)
    except ValueError as exc:
        return VersionCheckResult("failed", f"本地版本信息无效：{exc}", local_version)

    settings = app.get("version_check", {})
    if not isinstance(settings, dict) or not settings.get("enabled", False):
        return VersionCheckResult("disabled", "未启用云端版本检查。", local_version)

    config_file = str(settings.get("config_file", "")).strip()
    if not config_file:
        return VersionCheckResult("disabled", "未配置云端版本检查位置。", local_version)
    download_folder = str(settings.get("download_folder", "")).strip()
    try:
        timeout = float(settings.get("timeout_seconds", 3))
        if timeout <= 0:
            raise ValueError("超时时间必须大于 0 秒")
        remote = _read_with_timeout(Path(config_file), timeout)
        release = remote.get("release")
        if not isinstance(release, dict):
            raise ValueError("云端配置缺少 release 段")
        latest = str(release.get("latest_version", "")).strip()
        minimum = str(release.get("minimum_supported_version", "")).strip()
        latest_tuple = version_tuple(latest)
        minimum_tuple = version_tuple(minimum)
        if minimum_tuple > latest_tuple:
            raise ValueError("云端最低支持版本不能高于最新版本")
    except Exception as exc:
        return VersionCheckResult("failed", f"云端版本检查失败，无法确认是否最新：{exc}", local_version, download_folder=download_folder)

    note = str(release.get("release_note", "")).strip()
    if local < minimum_tuple:
        state, message = "update_required", "当前版本低于云端最低支持版本，请升级后再继续。"
    elif local < latest_tuple:
        state, message = "update_available", "发现新版程序，建议升级。"
    elif local == latest_tuple:
        state, message = "current", "当前已是最新版本。"
    else:
        state, message = "ahead", "本地程序版本高于云端发布版本。"
    return VersionCheckResult(state, message, local_version, latest, minimum, note, download_folder)
