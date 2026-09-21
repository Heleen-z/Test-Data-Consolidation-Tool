from __future__ import annotations

import pytest

from testdata_tool import version_check
from testdata_tool.version_check import check_remote_version, version_tuple


def _settings(config_file="", **overrides):
    settings = {"enabled": True, "config_file": str(config_file), "timeout_seconds": 1, "download_folder": r"\\server\release"}
    settings.update(overrides)
    return {"version_check": settings}


def _remote(path, latest="1.1.1", minimum="1.1.0", note="Release note"):
    path.write_text("release:\n" f"  latest_version: {latest}\n" f"  minimum_supported_version: {minimum}\n" f"  release_note: {note}\n", encoding="utf-8")


@pytest.mark.parametrize(("local", "latest", "minimum", "state"), [("1.1.1", "1.1.1", "1.1.0", "current"), ("1.1.0", "1.1.1", "1.1.0", "update_available"), ("1.0.9", "1.1.1", "1.1.0", "update_required"), ("1.2.0", "1.1.1", "1.1.0", "ahead")])
def test_remote_version_states(tmp_path, local, latest, minimum, state):
    remote = tmp_path / "config.yaml"
    _remote(remote, latest, minimum)
    result = check_remote_version(_settings(remote), local)
    assert result.state == state
    assert result.download_folder == r"\\server\release"


def test_version_comparison_is_numeric():
    assert version_tuple("1.1.10") > version_tuple("1.1.9")


@pytest.mark.parametrize("local,latest,minimum", [("1.1", "1.1.1", "1.0.0"), ("1.0.0", "1.0", "1.0.0"), ("1.0.0", "1.0.0", "1.0")])
def test_invalid_version_is_a_non_blocking_failure(tmp_path, local, latest, minimum):
    remote = tmp_path / "config.yaml"
    _remote(remote, latest, minimum)
    assert check_remote_version(_settings(remote), local).state == "failed"


def test_missing_or_disabled_configuration_does_not_check():
    assert check_remote_version(_settings(""), "1.1.1").state == "disabled"
    assert check_remote_version(_settings(enabled=False), "1.1.1").state == "disabled"


def test_missing_remote_config_is_a_non_blocking_failure(tmp_path):
    assert check_remote_version(_settings(tmp_path / "missing.yaml"), "1.1.1").state == "failed"


def test_invalid_remote_release_is_a_non_blocking_failure(tmp_path):
    remote = tmp_path / "config.yaml"
    _remote(remote, "1.0.0", "1.0.1")
    assert check_remote_version(_settings(remote), "1.0.0").state == "failed"


def test_malformed_remote_yaml_is_a_non_blocking_failure(tmp_path):
    remote = tmp_path / "config.yaml"
    remote.write_text("release: [", encoding="utf-8")
    assert check_remote_version(_settings(remote), "1.1.1").state == "failed"


def test_read_timeout_is_a_non_blocking_failure(tmp_path, monkeypatch):
    remote = tmp_path / "config.yaml"
    _remote(remote)

    def slow_read(path):
        import time
        time.sleep(0.1)
        return {"release": {"latest_version": "1.1.1", "minimum_supported_version": "1.1.0"}}

    monkeypatch.setattr(version_check, "_mapping_from_yaml", slow_read)
    result = check_remote_version(_settings(remote, timeout_seconds=0.01), "1.1.1")
    assert result.state == "failed"
    assert "超过" in result.message
