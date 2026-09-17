from pathlib import Path

from testdata_tool.config import AppConfig, project_root
from testdata_tool.paths import default_template_folder


def test_frozen_release_prefers_config_beside_executable(tmp_path, monkeypatch):
    executable = tmp_path / "Testing Data Consolidation Tool.exe"
    config = tmp_path / "config"
    config.mkdir()
    (config / "app_settings.yaml").write_text("defaults: {}\n", encoding="utf-8")
    monkeypatch.setattr("testdata_tool.config.sys.frozen", True, raising=False)
    monkeypatch.setattr("testdata_tool.config.sys.executable", str(executable))

    assert project_root() == tmp_path


def test_configured_relative_template_folder_uses_release_root(tmp_path, monkeypatch):
    template = tmp_path / "template"
    template.mkdir()
    monkeypatch.setattr("testdata_tool.paths.load_preferences", lambda: {})
    config = AppConfig(
        root=tmp_path,
        app={"defaults": {"template_folder": "template"}},
        test_types={"test_types": {}},
    )

    assert default_template_folder(config) == template
