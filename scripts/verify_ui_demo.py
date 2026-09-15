"""Exercise generated fixtures against the real UI without touching production logs."""
import json
import gc
import os
from pathlib import Path
import tempfile

from streamlit.testing.v1 import AppTest


def main():
    root = Path(__file__).resolve().parents[1]
    demo = root / "outputs" / "ui-demo"
    expected = json.loads((demo / "expected.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="ui-demo-check-") as temporary:
        os.environ["LOCALAPPDATA"] = temporary
        os.chdir(demo)
        from testdata_tool.config import load_config
        from testdata_tool.precheck import run_precheck
        from testdata_tool.pipeline import merge_prechecked
        config = load_config()
        # Demo sidecars created before the logging configuration was renamed
        # still use usage_logging.  Both forms must keep demo verification local.
        logging = config.app.get("logging", config.app.get("usage_logging", {}))
        assert logging.get("mode") == "off"
        checked = run_precheck(demo / "input", demo / "templates", Path(temporary) / "output", config)
        for item in checked.files:
            print(item.path.name, item.status, item.messages)
        assert checked.scanned_count == expected["scanned"]
        assert checked.valid_count == expected["mergeable"]
        result = merge_prechecked(checked, Path(temporary) / "output", config)
        assert result.type_rows == expected["rows"], result.type_rows
        app = AppTest.from_file(root / "src/testdata_tool/ui.py", default_timeout=60).run()
        assert not app.exception
        assert app.text_input[0].value == str(demo / "input")
        app.text_input[1].set_value(str(Path(temporary) / "ui-output"))
        next(b for b in app.button if b.label == "开始 Pre-check").click().run(timeout=60)
        assert not app.exception
        next(b for b in app.button if b.label == "开始合并").click().run(timeout=60)
        assert not app.exception
        assert len(app.download_button) == 3
        from testdata_tool.usage_logging import Outbox, queue_path
        assert Outbox(queue_path()).status()[0] == 0
        print("PASS: 8 files, 5 mergeable, 5301 rows, UI merge and downloads, no usage events")
        gc.collect()  # Release temporary SQLite handles before Windows directory cleanup.


if __name__ == "__main__":
    main()
