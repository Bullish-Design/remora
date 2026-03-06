from persistent_ids.id_format import graph_id_from_bytes, graph_id_to_bytes, new_graph_id, parse_graph_id


def test_parse_graph_id_from_python_comment() -> None:
    line = "def run():  # graph:id=1234abcd"
    assert parse_graph_id(line) == "1234abcd"


def test_parse_graph_id_from_markdown_html_comment() -> None:
    line = "## Title <!-- graph:id=abcdef123456 -->"
    assert parse_graph_id(line) == "abcdef123456"


def test_uuid_round_trip_bytes() -> None:
    graph_id = new_graph_id()
    raw = graph_id_to_bytes(graph_id)
    assert len(raw) == 16
    assert graph_id_from_bytes(raw) == graph_id
