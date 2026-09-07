from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest


def test_ui_starts_and_empty_paths_show_validation(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    ui_path = Path(__file__).resolve().parents[1] / "src" / "testdata_tool" / "ui.py"
    app = AppTest.from_file(ui_path, default_timeout=30).run()
    assert not app.exception
    assert app.title[0].value == "Testing Raw Data Consolidation"
    for field in app.text_input:
        field.set_value("")
    next(button for button in app.button if button.label == "开始 Pre-check").click().run()
    assert not app.exception
    assert any("请输入原始数据输入目录" in error.value for error in app.error)
    from testdata_tool.usage_logging import Outbox, queue_path
    assert Outbox(queue_path()).status()[0] == 0


def test_ui_full_precheck_merge_and_chart(tmp_path, monkeypatch):
    import json
    from testdata_tool.usage_logging import Outbox, queue_path
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    root = Path(__file__).resolve().parents[1]
    ui_path = root / "src" / "testdata_tool" / "ui.py"
    app = AppTest.from_file(ui_path, default_timeout=60).run()
    app.text_input[0].set_value(str(root / "tests" / "fixtures" / "raw"))
    app.text_input[1].set_value(str(tmp_path / "output"))
    app.text_input[2].set_value(str(root / "Raw data standard Title"))
    next(button for button in app.button if button.label == "开始 Pre-check").click().run(timeout=60)
    assert not app.exception
    assert any(metric.value == "1" for metric in app.metric)
    next(button for button in app.button if button.label == "开始合并").click().run(timeout=60)
    assert not app.exception
    assert any("合并文件" in success.value for success in app.success)
    assert len(app.download_button) == 3
    box = Outbox(queue_path())
    assert box.status()[0] == 1
    with box.connect() as db:
        payload = json.loads(db.execute("SELECT payload FROM events").fetchone()[0])
    assert payload["Title"] == "SUCCESS" and payload["RowCount"] > 0
    assert payload["ProjectName"] == "raw"
    app.run()
    assert box.status()[0] == 1  # Rendering/downloading existing results cannot create events.
    next(button for button in app.button if button.label == "开始合并").click().run(timeout=60)
    assert box.status()[0] == 2


@pytest.mark.parametrize("failure", ["merge", "export", "cache"])
def test_usage_failure_boundaries(tmp_path, monkeypatch, failure):
    from testdata_tool.usage_logging import Outbox, queue_path
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    root = Path(__file__).resolve().parents[1]
    app = AppTest.from_file(root / "src/testdata_tool/ui.py", default_timeout=60).run()
    app.text_input[0].set_value(str(root / "tests/fixtures/raw"))
    app.text_input[1].set_value(str(tmp_path / "output"))
    app.text_input[2].set_value(str(root / "Raw data standard Title"))
    next(button for button in app.button if button.label == "开始 Pre-check").click().run(timeout=60)
    def fail(*args, **kwargs):
        raise OSError("simulated failure")
    if failure == "merge":
        monkeypatch.setattr("testdata_tool.pipeline.merge_prechecked", fail)
    elif failure == "export":
        monkeypatch.setattr("testdata_tool.pipeline.export_workbook", fail)
    else:
        monkeypatch.setattr(Outbox, "enqueue", fail)
    next(button for button in app.button if button.label == "开始合并").click().run(timeout=60)
    assert not app.exception
    assert Outbox(queue_path()).status()[0] == 0
    if failure == "cache":
        assert any("合并文件" in item.value for item in app.success)
        assert any("本次使用记录未保存" in item.value for item in app.warning)
    else:
        assert any("合并失败" in item.value for item in app.error)
