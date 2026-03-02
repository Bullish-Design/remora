"""Tests for app.py — Stario app factory and handlers.

These tests verify the structural correctness of app.py.
Full import tests are skipped when Stario is not available (Python 3.13 env).
"""

from __future__ import annotations

import importlib
import sys

import pytest


# ── Module structure tests (work without Stario) ──


class TestAppModuleStructure:
    """Verify app.py exists and has the expected public API."""

    def test_app_file_exists(self) -> None:
        from pathlib import Path

        app_path = Path(__file__).parent.parent / "remora_demo" / "web" / "graph" / "app.py"
        assert app_path.exists(), f"app.py not found at {app_path}"

    def test_app_source_has_create_app(self) -> None:
        from pathlib import Path

        source = (Path(__file__).parent.parent / "remora_demo" / "web" / "graph" / "app.py").read_text()
        assert "def create_app(" in source

    def test_app_source_has_handler_factories(self) -> None:
        from pathlib import Path

        source = (Path(__file__).parent.parent / "remora_demo" / "web" / "graph" / "app.py").read_text()
        for name in ("def index(", "def subscribe(", "def agent_detail(", "def post_command(", "def event_stream("):
            assert name in source, f"Missing handler factory: {name}"

    def test_app_source_has_command_signals(self) -> None:
        from pathlib import Path

        source = (Path(__file__).parent.parent / "remora_demo" / "web" / "graph" / "app.py").read_text()
        assert "class CommandSignals" in source

    def test_app_source_routes(self) -> None:
        """Verify all expected routes are wired."""
        from pathlib import Path

        source = (Path(__file__).parent.parent / "remora_demo" / "web" / "graph" / "app.py").read_text()
        assert 'app.get("/"' in source
        assert 'app.get("/subscribe"' in source
        assert 'app.get("/agent/*"' in source
        assert 'app.get("/events"' in source
        assert 'app.post("/command"' in source

    def test_app_source_uses_safestring(self) -> None:
        """Views return strings — handlers must wrap in SafeString for w.patch."""
        from pathlib import Path

        source = (Path(__file__).parent.parent / "remora_demo" / "web" / "graph" / "app.py").read_text()
        assert "SafeString" in source

    def test_app_source_uses_asyncio_to_thread(self) -> None:
        """DB reads must be offloaded to avoid blocking the event loop."""
        from pathlib import Path

        source = (Path(__file__).parent.parent / "remora_demo" / "web" / "graph" / "app.py").read_text()
        assert "asyncio.to_thread" in source

    def test_app_returns_bridge(self) -> None:
        """create_app must return (app, bridge) so caller can start the bridge."""
        from pathlib import Path

        source = (Path(__file__).parent.parent / "remora_demo" / "web" / "graph" / "app.py").read_text()
        assert "return app, bridge" in source


# ── Full import tests (require Stario / Python 3.14) ──


stario_available = importlib.util.find_spec("stario") is not None
skip_no_stario = pytest.mark.skipif(not stario_available, reason="Stario not installed (Python 3.14 required)")


@skip_no_stario
class TestAppImport:
    """Tests that require Stario to be importable."""

    def test_import_app_module(self) -> None:
        from remora_demo.web.graph.app import create_app

        assert callable(create_app)

    def test_create_app_returns_tuple(self, tmp_path) -> None:
        from remora_demo.web.graph.app import create_app

        db_path = str(tmp_path / "test.db")
        app, bridge = create_app(db_path)
        assert app is not None
        assert bridge is not None
