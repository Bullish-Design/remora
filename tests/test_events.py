import pytest

def test_node_discovered_event_from_cst_node():
    from remora.core.discovery import CSTNode, compute_node_id, compute_source_hash
    from remora.core.events import NodeDiscoveredEvent

    node = CSTNode(
        node_id=compute_node_id("test.py", "function", "test.foo"),
        node_type="function", name="foo", full_name="test.foo",
        file_path="test.py", text="def foo(): pass",
        start_line=1, end_line=1, start_byte=0, end_byte=15,
        parent_id="abc123",
    )
    event = NodeDiscoveredEvent.from_cst_node(node)
    assert event.node_id == node.node_id
    assert event.source_code == node.text
    assert event.source_hash == compute_source_hash(node.text)
    assert event.parent_id == "abc123"
