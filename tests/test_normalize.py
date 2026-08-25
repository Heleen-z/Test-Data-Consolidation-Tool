from testdata_tool.normalize import match_headers, normalize_header


def test_normalize_header_space_case_and_width():
    assert normalize_header("  ＴＣＫ０１　 Value  ") == "tck01 value"


def test_alias_matching_is_explicit():
    mapping, errors = match_headers(
        ["Temperature [°C]"],
        ["Temperature [C]"],
        {"Temperature [°C]": ["Temperature [C]"]},
    )
    assert mapping == {"Temperature [°C]": "Temperature [C]"}
    assert not errors


def test_no_fuzzy_unit_matching():
    mapping, errors = match_headers(["Temperature [°C]"], ["Temperature [C]"])
    assert mapping == {}
    assert not errors

