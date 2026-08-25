from testdata_tool.export import safe_sheet_name


def test_safe_sheet_name_and_collision():
    existing = set()
    first = safe_sheet_name("T:09/very*long?name[abc]012345678901234567890", existing)
    second = safe_sheet_name("T:09/very*long?name[abc]012345678901234567890", existing)
    assert len(first) <= 31
    assert not any(character in first for character in "[]:*?/\\")
    assert first != second

