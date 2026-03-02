# tests/unit/test_lsp_db.py
"""Tests for RemoraDB — non-node operations (events, proposals, cursor_focus, etc.)."""

from __future__ import annotations

import pytest

from remora.lsp.db import RemoraDB
from remora.lsp.models import HumanChatEvent


@pytest.fixture
async def db(tmp_path):
    db = RemoraDB(str(tmp_path / "test.db"))
    yield db
    db.close()


@pytest.mark.asyncio
async def test_store_and_retrieve_event(db):
    event = HumanChatEvent(
        to_agent="rm_test1234",
        message="hello",
        correlation_id="corr_1",
        timestamp=1.0,
    )
    await db.store_event(event)
    events = await db.get_recent_events("rm_test1234", limit=5)
    assert len(events) == 1
    assert events[0].event_type == "HumanChatEvent"


@pytest.mark.asyncio
async def test_update_cursor_focus(db):
    await db.update_cursor_focus("rm_test1234", "file:///test.py", 10)
    focus = db.get_cursor_focus()
    assert focus is not None
    assert focus["agent_id"] == "rm_test1234"
    assert focus["line"] == 10
