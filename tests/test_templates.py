from pathlib import Path

from testdata_tool.config import load_config
from testdata_tool.templates import load_templates


def test_supplied_templates_are_detected():
    config = load_config()
    templates = load_templates(Path("Raw data standard Title"), config)
    assert set(templates) == {
        "FAKT",
        "GANTER",
        "MP_SHAKER",
        "SEOUL",
        "T09",
        "T12",
        "T13",
    }
    assert "TCK01" in templates["GANTER"].fields
    assert "X-Data [s]" in templates["MP_SHAKER"].fields
    assert all(template.fields for template in templates.values())

