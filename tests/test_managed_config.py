from __future__ import annotations

import hashlib
import json
from pathlib import Path
import zipfile

import pytest
import yaml

from testdata_tool.config import (
    ConfigError,
    is_app_update_available,
    is_app_update_required,
    load_config,
)
from testdata_tool.managed_config import load_local_operations


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_central_release(root: Path, template_source: Path) -> None:
    config_path = root / "configs" / "2026.09.001" / "operations.yaml"
    template_path = root / "templates" / "2026.09.003" / "TemplateBundle.zip"
    config_path.parent.mkdir(parents=True)
    template_path.parent.mkdir(parents=True)
    config_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "contact": {"owner": "Managed Support", "email": "managed@example.com"},
                "defaults": {"input_folder": "", "output_folder": ""},
                "ui": {"brand_title": "Managed Tool", "announcement": "Central notice"},
                "managed_templates": {
                    "required": True,
                    "download_label": "Download templates",
                    "update_message": "Updating",
                    "success_message": "Updated to {version}",
                },
                "support_links": {},
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    with zipfile.ZipFile(template_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for source in template_source.glob("*.xlsx"):
            archive.write(source, f"Raw data standard Title/{source.name}")
    manifest = {
        "schema_version": 1,
        "channel": "production",
        "published_at": "2026-09-01T10:00:00+08:00",
        "published_by": "administrator",
        "config": {
            "version": "2026.09.001",
            "path": "configs/2026.09.001/operations.yaml",
            "sha256": _sha256(config_path),
        },
        "templates": {
            "version": "2026.09.003",
            "path": "templates/2026.09.003/TemplateBundle.zip",
            "sha256": _sha256(template_path),
            "display_name": "Standard Templates",
        },
        "application": {
            "latest_version": "1.2.0",
            "minimum_supported_version": "1.0.0",
            "download_path": "app/1.2.0/Testing Data Consolidation Tool.exe",
            "release_note": "Managed configuration support",
        },
    }
    (root / "release-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def test_central_config_template_update_and_cache_fallback(tmp_path, monkeypatch):
    project_root = Path(__file__).resolve().parents[1]
    central = tmp_path / "central"
    central.mkdir()
    _make_central_release(central, project_root / "Raw data standard Title")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    monkeypatch.setenv("TESTDATA_TOOL_CONFIG_ROOT", str(central))

    config = load_config(project_root)
    assert config.config_source == "central"
    assert config.config_version == "2026.09.001"
    assert config.template_version == "2026.09.003"
    assert config.template_updated
    assert config.app["contact"]["email"] == "managed@example.com"
    assert config.managed_template_folder
    assert len(list(config.managed_template_folder.glob("*.xlsx"))) == 7
    assert config.template_bundle and config.template_bundle.is_file()
    assert is_app_update_available(config)
    assert not is_app_update_required(config)

    monkeypatch.setenv("TESTDATA_TOOL_CONFIG_ROOT", str(tmp_path / "offline"))
    cached = load_config(project_root)
    assert cached.config_source == "cache"
    assert cached.config_version == config.config_version
    assert cached.managed_template_folder == config.managed_template_folder
    assert Path(cached.app_download_path).is_absolute()
    assert cached.warnings


def test_first_start_without_central_or_cache_is_blocked(tmp_path, monkeypatch):
    project_root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    monkeypatch.setenv("TESTDATA_TOOL_CONFIG_ROOT", str(tmp_path / "missing"))
    with pytest.raises(ConfigError, match="本机没有有效缓存"):
        load_config(project_root)


def test_local_sidecar_bypasses_central_configuration(tmp_path, monkeypatch):
    project_root = Path(__file__).resolve().parents[1]
    sidecar = tmp_path / "local-config.yaml"
    sidecar.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "contact": {"owner": "Local Tester", "email": ""},
                "defaults": {"input_folder": "", "output_folder": "", "template_folder": "C:/Templates"},
                "ui": {"brand_title": "Local Test", "announcement": "Local"},
                "managed_templates": {"required": False},
                "support_links": {},
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("testdata_tool.managed_config.executable_folder", lambda: tmp_path)
    monkeypatch.setenv("TESTDATA_TOOL_CONFIG_ROOT", str(tmp_path / "missing"))

    operations = load_local_operations()
    config = load_config(project_root)

    assert operations and operations["defaults"]["template_folder"] == "C:/Templates"
    assert config.config_source == "local sidecar"
    assert config.config_version == "local-test"
    assert config.app["ui"]["brand_title"] == "Local Test"
    assert config.app["defaults"]["template_folder"] == "C:/Templates"


def test_operations_rejects_code_logic_keys(tmp_path, monkeypatch):
    project_root = Path(__file__).resolve().parents[1]
    central = tmp_path / "central"
    central.mkdir()
    _make_central_release(central, project_root / "Raw data standard Title")
    operations = central / "configs" / "2026.09.001" / "operations.yaml"
    operations.write_text("schema_version: 1\ntest_types: {}\n", encoding="utf-8")
    manifest = json.loads((central / "release-manifest.json").read_text(encoding="utf-8"))
    manifest["config"]["sha256"] = _sha256(operations)
    (central / "release-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    monkeypatch.setenv("TESTDATA_TOOL_CONFIG_ROOT", str(central))
    with pytest.raises(ConfigError, match="不允许"):
        load_config(project_root)
