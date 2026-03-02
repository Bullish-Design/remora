"""Tests for the command_queue DB operations."""

import json
import time

from remora.lsp.db import RemoraDB


class TestCommandQueue:
    def setup_method(self):
        self.db = RemoraDB(db_path=":memory:")

    def teardown_method(self):
        self.db.close()

    def test_table_exists(self):
        cursor = self.db.conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='command_queue'")
        assert cursor.fetchone() is not None

    def test_push_and_poll(self):
        self.db.push_command("chat", "agent_1", {"message": "hello"})
        commands = self.db.poll_commands(limit=10)
        assert len(commands) == 1
        assert commands[0]["command_type"] == "chat"
        assert commands[0]["agent_id"] == "agent_1"
        assert commands[0]["status"] == "pending"

    def test_poll_returns_only_pending(self):
        self.db.push_command("chat", "a1", {"message": "hi"})
        commands = self.db.poll_commands(limit=10)
        cmd_id = commands[0]["id"]
        self.db.mark_command_done(cmd_id)
        commands = self.db.poll_commands(limit=10)
        assert len(commands) == 0

    def test_mark_done_sets_processed_at(self):
        self.db.push_command("approve_proposal", "a1", {"proposal_id": "p1"})
        commands = self.db.poll_commands(limit=10)
        cmd_id = commands[0]["id"]
        self.db.mark_command_done(cmd_id)
        cursor = self.db.conn.cursor()
        cursor.execute("SELECT status, processed_at FROM command_queue WHERE id = ?", (cmd_id,))
        row = cursor.fetchone()
        assert row["status"] == "done"
        assert row["processed_at"] is not None

    def test_push_multiple_poll_ordered(self):
        self.db.push_command("chat", "a1", {"message": "first"})
        self.db.push_command("chat", "a2", {"message": "second"})
        commands = self.db.poll_commands(limit=10)
        assert len(commands) == 2
        assert commands[0]["agent_id"] == "a1"
        assert commands[1]["agent_id"] == "a2"
