# tests/unit/test_lsp_db.py
"""Tests for RemoraDB — non-node operations (events, proposals, cursor_focus, etc.)."""

from __future__ import annotations

import pytest

from remora.lsp.db import RemoraDB


@pytest.fixture
async def db(tmp_path):
    db = RemoraDB(str(tmp_path / "test.db"))
    yield db
    db.close()


@pytest.mark.asyncio
async def test_update_cursor_focus(db):
    await db.update_cursor_focus("rm_test1234", "file:///test.py", 10)
    focus = db.get_cursor_focus()
    assert focus is not None
    assert focus["agent_id"] == "rm_test1234"
    assert focus["line"] == 10


@pytest.mark.asyncio
async def test_store_proposal_with_file_path(db):
    """store_proposal accepts file_path; get_proposals_for_file works without nodes table."""
    await db.store_proposal(
        proposal_id="prop_1",
        agent_id="rm_agent1",
        old_source="def foo(): pass",
        new_source="def foo(): return 1",
        diff="- def foo(): pass\n+ def foo(): return 1",
        file_path="/tmp/test.py",
    )
    proposals = await db.get_proposals_for_file("/tmp/test.py")
    assert len(proposals) == 1
    assert proposals[0]["proposal_id"] == "prop_1"
    assert proposals[0]["agent_id"] == "rm_agent1"
    assert proposals[0]["file_path"] == "/tmp/test.py"


@pytest.mark.asyncio
async def test_get_proposals_for_file_no_nodes_table(db):
    """get_proposals_for_file returns proposals by file_path directly, no nodes JOIN."""
    # Store two proposals for different files
    await db.store_proposal(
        proposal_id="prop_a",
        agent_id="rm_a",
        old_source="old_a",
        new_source="new_a",
        diff="diff_a",
        file_path="/tmp/a.py",
    )
    await db.store_proposal(
        proposal_id="prop_b",
        agent_id="rm_b",
        old_source="old_b",
        new_source="new_b",
        diff="diff_b",
        file_path="/tmp/b.py",
    )
    # Only get proposals for a.py
    proposals = await db.get_proposals_for_file("/tmp/a.py")
    assert len(proposals) == 1
    assert proposals[0]["proposal_id"] == "prop_a"

    # Only pending proposals are returned
    await db.update_proposal_status("prop_a", "accepted")
    proposals = await db.get_proposals_for_file("/tmp/a.py")
    assert len(proposals) == 0


@pytest.mark.asyncio
async def test_proposal_lifecycle_without_pending_on_node(db):
    """Proposals work via status column — no pending_proposal_id on nodes needed."""
    await db.store_proposal(
        proposal_id="prop_1",
        agent_id="rm_agent1",
        old_source="old",
        new_source="new",
        diff="diff",
        file_path="/tmp/test.py",
    )
    # Proposal is pending
    p = await db.get_proposal("prop_1")
    assert p["status"] == "pending"

    # Accept it
    await db.update_proposal_status("prop_1", "accepted")
    p = await db.get_proposal("prop_1")
    assert p["status"] == "accepted"

    # No longer shows in pending proposals
    proposals = await db.get_proposals_for_file("/tmp/test.py")
    assert len(proposals) == 0

    # db should NOT have set_pending_proposal or clear_pending_proposal
    assert not hasattr(db, "set_pending_proposal")
    assert not hasattr(db, "clear_pending_proposal")


@pytest.mark.asyncio
async def test_no_nodes_table_or_methods(db):
    """RemoraDB should not have nodes table or node-related methods."""
    cursor = db.conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cursor.fetchall()}
    assert "nodes" not in tables
    assert "edges" in tables  # edges stay
    assert "proposals" in tables

    # Node methods should not exist
    assert not hasattr(db, "_normalize_node")
    assert not hasattr(db, "get_node")
    assert not hasattr(db, "get_nodes_for_file")
    assert not hasattr(db, "get_all_nodes")
    assert not hasattr(db, "get_node_at_position")
    assert not hasattr(db, "set_status")
    assert not hasattr(db, "get_neighborhood")
    assert not hasattr(db, "get_edges_for_nodes")
