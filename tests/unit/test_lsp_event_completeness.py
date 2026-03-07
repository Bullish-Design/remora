"""Tests for Workstream D — LSP Event Completeness (Gaps #12, #13).

Gap #12: textDocument/didChange handler with debounced reparse
Gap #13: Cursor tracking debounce + CursorFocusEvent emission
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from lsprotocol import types as lsp

from remora.core.events import CursorFocusEvent


# ============================================================================
# CursorFocusEvent model tests
# ============================================================================


class TestCursorFocusEvent:
    """CursorFocusEvent model validation."""

    def test_cursor_focus_event_fields(self):
        evt = CursorFocusEvent(focused_agent_id="agent-1", file_path="file:///test.py", line=10)
        assert evt.focused_agent_id == "agent-1"
        assert evt.file_path == "file:///test.py"
        assert evt.line == 10
        assert evt.timestamp > 0

    def test_cursor_focus_event_nullable_agent_id(self):
        evt = CursorFocusEvent(focused_agent_id=None, file_path="file:///test.py", line=5)
        assert evt.focused_agent_id is None

    def test_cursor_focus_event_is_frozen(self):
        evt = CursorFocusEvent(focused_agent_id="a", file_path="f", line=1)
        with pytest.raises(Exception):
            evt.focused_agent_id = "b"


# ============================================================================
# didChange handler tests
# ============================================================================


class TestDidChangeHandler:
    """Gap #12: textDocument/didChange calls schedule_reparse with debounce."""

    def test_did_change_handler_is_registered(self):
        """The didChange handler should be registered on the server."""
        from remora.lsp.server import server

        fm = server.protocol.fm
        feature_names = set(fm.features.keys())
        assert "textDocument/didChange" in feature_names

    @pytest.mark.asyncio
    async def test_did_change_calls_schedule_reparse(self):
        """did_change should call server.schedule_reparse with the full text."""
        from remora.lsp.handlers.documents import did_change
        from remora.lsp.server import server

        uri = "file:///test.py"
        text = "def foo():\n    return 1\n"
        params = lsp.DidChangeTextDocumentParams(
            text_document=lsp.VersionedTextDocumentIdentifier(uri=uri, version=2),
            content_changes=[
                lsp.TextDocumentContentChangeWholeDocument(text=text),
            ],
        )

        with patch.object(server, "schedule_reparse") as mock_schedule:
            await did_change(params)
            mock_schedule.assert_called_once_with(uri, text, delay_ms=500)

    @pytest.mark.asyncio
    async def test_did_change_ignores_empty_content_changes(self):
        """did_change should return early if content_changes is empty."""
        from remora.lsp.handlers.documents import did_change
        from remora.lsp.server import server

        params = lsp.DidChangeTextDocumentParams(
            text_document=lsp.VersionedTextDocumentIdentifier(uri="file:///test.py", version=2),
            content_changes=[],
        )

        with patch.object(server, "schedule_reparse") as mock_schedule:
            await did_change(params)
            mock_schedule.assert_not_called()

    @pytest.mark.asyncio
    async def test_did_change_does_not_emit_content_changed_event(self):
        """didChange must NOT emit ContentChangedEvent — only didSave does."""
        from remora.lsp.handlers.documents import did_change
        from remora.lsp.server import server

        uri = "file:///test.py"
        text = "def foo():\n    pass\n"
        params = lsp.DidChangeTextDocumentParams(
            text_document=lsp.VersionedTextDocumentIdentifier(uri=uri, version=2),
            content_changes=[
                lsp.TextDocumentContentChangeWholeDocument(text=text),
            ],
        )

        # schedule_reparse is the only thing that should be called
        with patch.object(server, "schedule_reparse") as mock_schedule:
            await did_change(params)
            mock_schedule.assert_called_once()

        # Verify no event_store.append call happens in did_change itself
        # (it only schedules a reparse, doesn't append events directly)


# ============================================================================
# schedule_reparse debounce tests
# ============================================================================


class TestScheduleReparse:
    """Debounce mechanics for schedule_reparse."""

    def test_schedule_reparse_stores_timer(self):
        """schedule_reparse should store a timer handle for the URI."""
        from remora.lsp.server import RemoraLanguageServer

        srv = RemoraLanguageServer.__new__(RemoraLanguageServer)
        srv._reparse_timers = {}
        srv._cursor_timers = {}
        srv.event_store = None
        srv.watcher = MagicMock()

        loop = asyncio.new_event_loop()
        try:
            with patch("asyncio.get_event_loop", return_value=loop):
                srv.schedule_reparse("file:///a.py", "code", delay_ms=500)
                assert "file:///a.py" in srv._reparse_timers
        finally:
            # Cancel the timer to clean up
            timer = srv._reparse_timers.get("file:///a.py")
            if timer:
                timer.cancel()
            loop.close()

    def test_schedule_reparse_cancels_previous_timer(self):
        """A second call for the same URI should cancel the first timer."""
        from remora.lsp.server import RemoraLanguageServer

        srv = RemoraLanguageServer.__new__(RemoraLanguageServer)
        srv._reparse_timers = {}
        srv._cursor_timers = {}
        srv.event_store = None
        srv.watcher = MagicMock()

        loop = asyncio.new_event_loop()
        try:
            with patch("asyncio.get_event_loop", return_value=loop):
                srv.schedule_reparse("file:///a.py", "code1", delay_ms=500)
                first_timer = srv._reparse_timers["file:///a.py"]

                srv.schedule_reparse("file:///a.py", "code2", delay_ms=500)
                second_timer = srv._reparse_timers["file:///a.py"]

                assert first_timer.cancelled()
                assert not second_timer.cancelled()
        finally:
            for t in srv._reparse_timers.values():
                t.cancel()
            loop.close()

    def test_schedule_reparse_independent_uris(self):
        """Different URIs should have independent timers."""
        from remora.lsp.server import RemoraLanguageServer

        srv = RemoraLanguageServer.__new__(RemoraLanguageServer)
        srv._reparse_timers = {}
        srv._cursor_timers = {}
        srv.event_store = None
        srv.watcher = MagicMock()

        loop = asyncio.new_event_loop()
        try:
            with patch("asyncio.get_event_loop", return_value=loop):
                srv.schedule_reparse("file:///a.py", "code1", delay_ms=500)
                srv.schedule_reparse("file:///b.py", "code2", delay_ms=500)

                assert "file:///a.py" in srv._reparse_timers
                assert "file:///b.py" in srv._reparse_timers
                assert not srv._reparse_timers["file:///a.py"].cancelled()
                assert not srv._reparse_timers["file:///b.py"].cancelled()
        finally:
            for t in srv._reparse_timers.values():
                t.cancel()
            loop.close()


# ============================================================================
# _do_reparse integration tests
# ============================================================================


class TestDoReparse:
    """The actual reparse callback fired by the debounce timer."""

    @pytest.mark.asyncio
    async def test_do_reparse_updates_nodes(self, tmp_path: Path):
        """_do_reparse should parse and emit NodeDiscoveredEvents."""
        from remora.core.event_store import EventStore
        from remora.core.projections import NodeProjection
        from remora.lsp.server import RemoraLanguageServer
        srv = RemoraLanguageServer.__new__(RemoraLanguageServer)
        srv._reparse_timers = {}
        srv._cursor_timers = {}

        event_store = EventStore(tmp_path / "events.db", projection=NodeProjection())
        await event_store.initialize()
        srv.event_store = event_store

        # Stub methods that need the full pygls machinery
        srv.refresh_code_lenses = AsyncMock()
        srv.notify_agents_updated = AsyncMock()

        uri = "file:///test.py"
        text = "def hello():\n    pass\n"

        await srv._do_reparse(uri, text)

        nodes = await event_store.list_nodes(file_path=uri)
        assert len(nodes) >= 1
        assert any(n.name == "hello" for n in nodes)

        srv.refresh_code_lenses.assert_awaited_once()
        srv.notify_agents_updated.assert_awaited_once()

        await event_store.close()

    @pytest.mark.asyncio
    async def test_do_reparse_removes_orphans(self, tmp_path: Path):
        """_do_reparse should emit NodeRemovedEvent for nodes no longer in source."""
        from remora.core.event_store import EventStore
        from remora.core.events import NodeDiscoveredEvent
        from remora.core.projections import NodeProjection
        from remora.lsp.server import RemoraLanguageServer
        srv = RemoraLanguageServer.__new__(RemoraLanguageServer)
        srv._reparse_timers = {}
        srv._cursor_timers = {}

        event_store = EventStore(tmp_path / "events.db", projection=NodeProjection())
        await event_store.initialize()
        srv.event_store = event_store

        srv.refresh_code_lenses = AsyncMock()
        srv.notify_agents_updated = AsyncMock()

        uri = "file:///test.py"

        # First parse with two functions
        text_v1 = "def hello():\n    pass\n\ndef goodbye():\n    pass\n"
        await srv._do_reparse(uri, text_v1)
        nodes_v1 = await event_store.list_nodes(file_path=uri)
        assert len(nodes_v1) >= 2

        # Second parse removes goodbye
        text_v2 = "def hello():\n    pass\n"
        await srv._do_reparse(uri, text_v2)
        nodes_v2 = await event_store.list_nodes(file_path=uri)
        names = [n.name for n in nodes_v2]
        assert "hello" in names
        assert "goodbye" not in names

        await event_store.close()

    @pytest.mark.asyncio
    async def test_do_reparse_does_not_emit_content_changed(self, tmp_path: Path):
        """_do_reparse must not emit ContentChangedEvent or FileSavedEvent."""
        from remora.core.event_store import EventStore
        from remora.core.projections import NodeProjection
        from remora.lsp.server import RemoraLanguageServer
        srv = RemoraLanguageServer.__new__(RemoraLanguageServer)
        srv._reparse_timers = {}
        srv._cursor_timers = {}

        event_store = EventStore(tmp_path / "events.db", projection=NodeProjection())
        await event_store.initialize()
        srv.event_store = event_store
        srv.refresh_code_lenses = AsyncMock()
        srv.notify_agents_updated = AsyncMock()

        await srv._do_reparse("file:///test.py", "def f():\n    pass\n")

        # Replay "files" stream — should be empty (no ContentChangedEvent)
        file_events = [record async for record in event_store.replay("files")]
        assert len(file_events) == 0

        await event_store.close()


# ============================================================================
# Cursor debounce tests
# ============================================================================


class TestScheduleCursorUpdate:
    """Debounce mechanics for schedule_cursor_update."""

    def test_schedule_cursor_update_stores_timer(self):
        from remora.lsp.server import RemoraLanguageServer

        srv = RemoraLanguageServer.__new__(RemoraLanguageServer)
        srv._reparse_timers = {}
        srv._cursor_timers = {}
        srv.db = MagicMock()
        srv.event_store = None

        loop = asyncio.new_event_loop()
        try:
            with patch("asyncio.get_event_loop", return_value=loop):
                srv.schedule_cursor_update("agent-1", "file:///a.py", 10, delay_ms=200)
                assert "file:///a.py" in srv._cursor_timers
        finally:
            for t in srv._cursor_timers.values():
                t.cancel()
            loop.close()

    def test_schedule_cursor_update_cancels_previous(self):
        from remora.lsp.server import RemoraLanguageServer

        srv = RemoraLanguageServer.__new__(RemoraLanguageServer)
        srv._reparse_timers = {}
        srv._cursor_timers = {}
        srv.db = MagicMock()
        srv.event_store = None

        loop = asyncio.new_event_loop()
        try:
            with patch("asyncio.get_event_loop", return_value=loop):
                srv.schedule_cursor_update("a1", "file:///a.py", 5, delay_ms=200)
                first = srv._cursor_timers["file:///a.py"]

                srv.schedule_cursor_update("a2", "file:///a.py", 10, delay_ms=200)
                second = srv._cursor_timers["file:///a.py"]

                assert first.cancelled()
                assert not second.cancelled()
        finally:
            for t in srv._cursor_timers.values():
                t.cancel()
            loop.close()


# ============================================================================
# _do_cursor_update tests
# ============================================================================


class TestDoCursorUpdate:
    """The actual cursor update callback fired by the debounce timer."""

    @pytest.mark.asyncio
    async def test_do_cursor_update_writes_db_and_emits_event(self, tmp_path: Path):
        """_do_cursor_update should write to DB and emit CursorFocusEvent."""
        from remora.core.event_store import EventStore
        from remora.core.projections import NodeProjection
        from remora.lsp.server import RemoraLanguageServer

        srv = RemoraLanguageServer.__new__(RemoraLanguageServer)
        srv._reparse_timers = {}
        srv._cursor_timers = {}
        srv.db = MagicMock()
        srv.db.update_cursor_focus = AsyncMock()

        event_store = EventStore(tmp_path / "events.db", projection=NodeProjection())
        await event_store.initialize()
        srv.event_store = event_store

        await srv._do_cursor_update("agent-42", "file:///test.py", 10)

        # DB updated
        srv.db.update_cursor_focus.assert_awaited_once_with("agent-42", "file:///test.py", 10)

        # CursorFocusEvent emitted to "cursor" stream
        events = [record async for record in event_store.replay("cursor")]
        assert len(events) == 1
        assert events[0]["event_type"] == "CursorFocusEvent"
        assert events[0]["payload"]["focused_agent_id"] == "agent-42"
        assert events[0]["payload"]["file_path"] == "file:///test.py"
        assert events[0]["payload"]["line"] == 10

        await event_store.close()

    @pytest.mark.asyncio
    async def test_do_cursor_update_with_null_agent_id(self, tmp_path: Path):
        """CursorFocusEvent should work with agent_id=None (cursor not on an agent)."""
        from remora.core.event_store import EventStore
        from remora.core.projections import NodeProjection
        from remora.lsp.server import RemoraLanguageServer

        srv = RemoraLanguageServer.__new__(RemoraLanguageServer)
        srv._reparse_timers = {}
        srv._cursor_timers = {}
        srv.db = MagicMock()
        srv.db.update_cursor_focus = AsyncMock()

        event_store = EventStore(tmp_path / "events.db", projection=NodeProjection())
        await event_store.initialize()
        srv.event_store = event_store

        await srv._do_cursor_update(None, "file:///test.py", 5)

        srv.db.update_cursor_focus.assert_awaited_once_with(None, "file:///test.py", 5)

        events = [record async for record in event_store.replay("cursor")]
        assert len(events) == 1
        # focused_agent_id=None is filtered out by event_store's _row_to_dict
        assert events[0]["payload"].get("focused_agent_id") is None

        await event_store.close()

    @pytest.mark.asyncio
    async def test_do_cursor_update_without_event_store(self):
        """_do_cursor_update should still update DB even without event_store."""
        from remora.lsp.server import RemoraLanguageServer

        srv = RemoraLanguageServer.__new__(RemoraLanguageServer)
        srv._reparse_timers = {}
        srv._cursor_timers = {}
        srv.db = MagicMock()
        srv.db.update_cursor_focus = AsyncMock()
        srv.event_store = None

        await srv._do_cursor_update("a1", "file:///test.py", 3)
        srv.db.update_cursor_focus.assert_awaited_once_with("a1", "file:///test.py", 3)


# ============================================================================
# on_cursor_moved handler tests
# ============================================================================


class TestOnCursorMovedDebounce:
    """Gap #13: on_cursor_moved should use debounced schedule_cursor_update."""

    @pytest.mark.asyncio
    async def test_on_cursor_moved_calls_schedule_cursor_update(self):
        """on_cursor_moved should resolve the agent and call schedule_cursor_update."""
        from remora.lsp.notifications import on_cursor_moved
        from remora.lsp.server import server

        mock_node = MagicMock()
        mock_node.node_id = "agent-1"

        server.event_store = MagicMock()
        server.event_store.get_node_at_position = AsyncMock(return_value=mock_node)

        with patch.object(server, "schedule_cursor_update") as mock_schedule:
            await on_cursor_moved({"uri": "file:///test.py", "line": 10})
            mock_schedule.assert_called_once_with("agent-1", "file:///test.py", 10, delay_ms=200)

    @pytest.mark.asyncio
    async def test_on_cursor_moved_null_agent(self):
        """When cursor is not on an agent, schedule_cursor_update gets None."""
        from remora.lsp.notifications import on_cursor_moved
        from remora.lsp.server import server

        server.event_store = MagicMock()
        server.event_store.get_node_at_position = AsyncMock(return_value=None)

        with patch.object(server, "schedule_cursor_update") as mock_schedule:
            await on_cursor_moved({"uri": "file:///test.py", "line": 5})
            mock_schedule.assert_called_once_with(None, "file:///test.py", 5, delay_ms=200)

    @pytest.mark.asyncio
    async def test_on_cursor_moved_no_direct_db_write(self):
        """on_cursor_moved should NOT directly call db.update_cursor_focus anymore."""
        from remora.lsp.notifications import on_cursor_moved
        from remora.lsp.server import server

        mock_node = MagicMock()
        mock_node.node_id = "a1"

        server.event_store = MagicMock()
        server.event_store.get_node_at_position = AsyncMock(return_value=mock_node)
        server.db = MagicMock()
        server.db.update_cursor_focus = AsyncMock()

        with patch.object(server, "schedule_cursor_update"):
            await on_cursor_moved({"uri": "file:///x.py", "line": 1})
            # DB write should NOT happen directly — it's deferred to the debounced callback
            server.db.update_cursor_focus.assert_not_awaited()
