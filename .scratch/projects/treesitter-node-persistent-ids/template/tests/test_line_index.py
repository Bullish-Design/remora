from persistent_ids.line_index import LineIndex


def test_line_at_row_in_range() -> None:
    index = LineIndex(b"line0\nline1\nline2")
    assert index.line_at_row(1) == "line1"


def test_line_at_row_out_of_range() -> None:
    index = LineIndex(b"line0")
    assert index.line_at_row(4) == ""


def test_line_count() -> None:
    index = LineIndex(b"a\nb")
    assert index.line_count() == 2
