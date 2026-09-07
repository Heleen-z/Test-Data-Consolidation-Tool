import pandas as pd
import pytest

from testdata_tool.charting import (
    RANGE_SLIDER_THICKNESS,
    build_chart_definitions,
    build_linked_chart_html,
    classify_channels,
    has_chart_numeric_values,
)


TEMPERATURE_RULES = {
    "name_contains": ["temp", "temperature", "tck", "ts", "egt", "温度"],
    "name_equals": ["ts"],
    "name_prefixes": ["t burner", "t gas"],
    "numeric_prefixes": ["t", "ts", "tck", "tc", "egt"],
    "units": ["c", "degc", "celsius", "f", "degf", "k", "kelvin"],
}


@pytest.mark.parametrize(
    ("channel", "expected_temperature"),
    [
        ("TCK01", True),
        ("TCK_01", True),
        ("Temperature actual value", True),
        ("Ts 1", True),
        ("T1", True),
        ("T1_1", True),
        ("T Burner", True),
        ("T gas in", True),
        ("Pressure [degC]", True),
        ("EGT-01", True),
        ("热电偶 温度", True),
        ("TC_03", True),
        ("R_EC.SPEED", False),
        ("R_EC.TORQUE", False),
        ("R_EC.POWER", False),
        ("ACCELERATION", False),
        ("Input_Vib tracking", False),
        ("Toal Flow", False),
    ],
)
def test_classify_channels(channel, expected_temperature):
    temperature, other = classify_channels([channel], TEMPERATURE_RULES)
    assert bool(temperature) is expected_temperature
    assert bool(other) is not expected_temperature


def test_classify_channels_honours_custom_rules():
    temperature, other = classify_channels(
        ["Heat Probe", "Speed"], {"name_contains": ["heat"]}
    )
    assert temperature == ["Heat Probe"]
    assert other == ["Speed"]


def test_classify_channels_does_not_make_every_channel_temperature_for_cjk_rule():
    temperature, other = classify_channels(
        ["温度 A", "R_EC.SPEED"], {"name_contains": ["温度"]}
    )
    assert temperature == ["温度 A"]
    assert other == ["R_EC.SPEED"]


def test_chart_numeric_compatibility():
    values = pd.Series(["１，２５", "1,234.5", "无效"])
    assert has_chart_numeric_values(values)


def test_mixed_channels_create_linked_charts_with_independent_y_bounds():
    frame = pd.DataFrame(
        {
            "__axis_value": [0, 1, 2],
            "__source_id": ["A", "A", "A"],
            "TCK01": [100.0, 300.0, 200.0],
            "R_EC.SPEED": [800.0, 810.0, 820.0],
            "R_EC.TORQUE": [10.0, 12.0, 11.0],
        }
    )
    definitions = build_chart_definitions(
        frame, ["TCK01", "R_EC.SPEED", "R_EC.TORQUE"], TEMPERATURE_RULES
    )
    assert [item.title for item in definitions] == ["温度通道", "其他通道"]
    assert definitions[0].y_bounds != definitions[1].y_bounds
    for definition in definitions:
        slider = definition.figure["layout"]["xaxis"]["rangeslider"]
        assert slider["visible"] is True
        assert slider["thickness"] == RANGE_SLIDER_THICKNESS
        assert slider["yaxis"]["rangemode"] == "auto"


def test_empty_and_single_group_data_are_handled_without_empty_charts():
    frame = pd.DataFrame(
        {
            "__axis_value": [0, 1],
            "__source_id": ["A", "A"],
            "TCK01": [None, None],
            "Speed": [1.0, 1.0],
        }
    )
    definitions = build_chart_definitions(frame, ["TCK01", "Speed"], TEMPERATURE_RULES)
    assert [item.title for item in definitions] == ["其他通道"]
    low, high = definitions[0].y_bounds
    assert low < 1.0 < high


def test_html_contains_offline_plotly_and_linked_control_contract():
    frame = pd.DataFrame(
        {
            "__axis_value": [0, 1],
            "__source_id": ["A", "A"],
            "TCK01": [10.0, 20.0],
            "Speed": [1.0, 2.0],
        }
    )
    html = build_linked_chart_html(
        build_chart_definitions(frame, ["TCK01", "Speed"], TEMPERATURE_RULES)
    )
    assert "plotly.js" in html
    assert "vertical-handle high" in html
    assert "vertical-selection" in html
    assert "installXLink" in html
    assert "syncingX" in html
    assert "quick-export" in html
    assert "Plotly.toImage" in html
    assert "<script src=" not in html


def test_cycle_export_uses_its_dedicated_label_and_window_logic():
    frame = pd.DataFrame(
        {"__axis_value": [0, 1], "__source_id": ["A", "A"], "Speed": [1.0, 2.0]}
    )
    html = build_linked_chart_html(
        build_chart_definitions(frame, ["Speed"], TEMPERATURE_RULES),
        cycles_quick_export=True,
    )
    assert "导出当前 10 个轮次高清截图" in html
    assert "Number(current[0])+10" in html
    assert "trend-10-cycles.png" in html
