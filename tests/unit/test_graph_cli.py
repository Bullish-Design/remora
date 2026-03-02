# tests/unit/test_graph_cli.py
"""Tests for the graph viewer CLI entry point."""

import subprocess
import sys


class TestCLI:
    def test_help_flag(self):
        result = subprocess.run(
            [sys.executable, "-m", "remora_demo.graph", "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        assert "--port" in result.stdout
        assert "--db" in result.stdout
