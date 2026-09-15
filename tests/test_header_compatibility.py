from __future__ import annotations

from testdata_tool.normalize import match_headers, normalize_header
from testdata_tool.parsers.tabular import TabularParser, detect_encoding


def test_normalize_header_handles_real_world_unit_and_spacing_variants():
    canonical = "Temperature actual value [°C]"
    variants = [
        " Temperature\u00a0actual-value [° C] ",
        "Temperature_actual_value (℃)",
        "Temperature actual value [ｰC]",
        "Temperature\u200b actual value [ºC]",
        "Temperature actual value [癈]",
    ]
    for variant in variants:
        mapping, errors = match_headers([canonical], [variant])
        assert not errors
        assert mapping == {canonical: variant}


def test_normalize_header_keeps_ordinary_japanese_text_intact():
    assert normalize_header("テストー名称") == normalize_header("テストー名称")
    assert normalize_header("テストー名称") != normalize_header("テスト°名称")


def test_cp1252_headers_are_not_misdetected_as_gb18030(tmp_path):
    path = tmp_path / "fakt_cp1252.txt"
    path.write_bytes(
        "Runtime [ms];Temperature actual value [°C]\n0;20.5\n".encode("cp1252")
    )

    assert detect_encoding(path) == "cp1252"
    inspection = TabularParser().inspect(
        path,
        ["Runtime [ms]", "Temperature actual value [°C]"],
        ["Runtime [ms]"],
    )
    assert inspection.columns == ["Runtime [ms]", "Temperature actual value [°C]"]
    mapping, errors = match_headers(
        ["Runtime [ms]", "Temperature actual value [°C]"], inspection.columns
    )
    assert not errors
    assert len(mapping) == 2


def test_gb18030_chinese_headers_remain_detectable(tmp_path):
    path = tmp_path / "chinese.txt"
    path.write_bytes("时间;温度\n0;20\n".encode("gb18030"))
    assert detect_encoding(path) == "gb18030"
