from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_ui_starts_and_empty_paths_show_validation(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    ui_path = Path(__file__).resolve().parents[1] / "src" / "testdata_tool" / "ui.py"
    app = AppTest.from_file(ui_path, default_timeout=30).run()
    assert not app.exception
    assert app.title[0].value == "Testing Raw Data Consolidation"
    for field in app.text_input:
        field.set_value("")
    app.button[0].click().run()
    assert not app.exception
    assert any("请输入原始数据输入目录" in error.value for error in app.error)


def test_ui_full_precheck_merge_and_chart(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    root = Path(__file__).resolve().parents[1]
    ui_path = root / "src" / "testdata_tool" / "ui.py"
    app = AppTest.from_file(ui_path, default_timeout=60).run()
    app.text_input[0].set_value(str(root / "tests" / "fixtures" / "raw"))
    app.text_input[1].set_value(str(tmp_path / "output"))
    app.text_input[2].set_value(str(root / "Raw data standard Title"))
    app.button[0].click().run(timeout=60)
    assert not app.exception
    assert any(metric.value == "1" for metric in app.metric)
    app.button[1].click().run(timeout=60)
    assert not app.exception
    assert any("合并文件" in success.value for success in app.success)
    assert len(app.download_button) == 3
