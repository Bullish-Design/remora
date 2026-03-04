# tests/unit/test_command_polling.py
"""Tests for LSP command queue polling dispatch."""

import json
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from remora.lsp.db import RemoraDB


class TestCommandPolling:
    def setup_method(self):
        self.db = RemoraDB(db_path=":memory:")

    def teardown_method(self):
        self.db.close()

    def test_push_and_poll_roundtrip(self):
        self.db.push_command("chat", "agent1", {"message": "hello"})
        cmds = self.db.poll_commands(limit=5)
        assert len(cmds) == 1
        assert cmds[0]["command_type"] == "chat"
        parsed = json.loads(cmds[0]["payload"])
        assert parsed["message"] == "hello"

    def test_mark_done_removes_from_poll(self):
        self.db.push_command("chat", "a1", {"msg": "hi"})
        cmds = self.db.poll_commands()
        self.db.mark_command_done(cmds[0]["id"])
        assert self.db.poll_commands() == []
