"""Tests for Hub models."""

from datetime import datetime, timezone

from remora.hub.models import FileIndex, HubStatus, NodeState


class TestNodeState:
    def test_create_function_node(self):
        state = NodeState(
            key="node:/project/foo.py:bar",
            file_path="/project/foo.py",
            node_name="bar",
            node_type="function",
            source_hash="abc123",
            file_hash="def456",
            signature="def bar(x: int) -> str",
            update_source="file_change",
        )

        assert state.node_type == "function"
        assert state.signature == "def bar(x: int) -> str"
        assert state.version == 1

    def test_inherits_timestamps(self):
        state = NodeState(
            key="node:/project/foo.py:bar",
            file_path="/project/foo.py",
            node_name="bar",
            node_type="function",
            source_hash="abc123",
            file_hash="def456",
            update_source="cold_start",
        )

        assert hasattr(state, "created_at")
        assert hasattr(state, "updated_at")
        assert hasattr(state, "version")
        assert isinstance(state.created_at, float)

    def test_serializes_to_json(self):
        state = NodeState(
            key="node:/project/foo.py:bar",
            file_path="/project/foo.py",
            node_name="bar",
            node_type="function",
            source_hash="abc123",
            file_hash="def456",
            update_source="cold_start",
        )

        json_str = state.model_dump_json()
        assert "foo.py" in json_str
        assert "bar" in json_str


class TestFileIndex:
    def test_create_file_index(self):
        index = FileIndex(
            file_path="/project/foo.py",
            file_hash="abc123",
            node_count=5,
            last_scanned=datetime.now(timezone.utc),
        )

        assert index.node_count == 5
        assert index.file_hash == "abc123"


class TestHubStatus:
    def test_create_status(self):
        status = HubStatus(
            running=True,
            pid=1234,
            project_root="/project",
        )

        assert status.running is True
        assert status.pid == 1234
        assert status.project_root == "/project"
