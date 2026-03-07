"""Tests for remora CLI commands.

Covers:
- swarm start (config error, headless mode, LSP mode)
- swarm reconcile (success output, config error)
- swarm list (no state file, empty, with agents)
- swarm emit (valid events, invalid JSON, unknown type)
- serve (config error, delegates to uvicorn)
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from remora.cli.main import main
from remora.core.config import ConfigError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _invoke(*args: str, **kwargs: Any) -> Any:
    """Invoke the CLI with the given args."""
    runner = CliRunner()
    return runner.invoke(main, list(args), catch_exceptions=False, **kwargs)


# =========================================================================
# 1. swarm list
# =========================================================================


class TestSwarmList:
    """Tests for `remora swarm list`."""

    def test_no_state_file(self, tmp_path: Path):
        """When no event store DB exists, shows helpful message."""
        result = _invoke("swarm", "list", "--project-root", str(tmp_path))
        assert result.exit_code == 0
        assert "No event store found" in result.output

    def test_empty_agents(self, tmp_path: Path):
        """When event store exists but no agents, shows 'No agents found'."""
        # Create the events.db file so the existence check passes
        remora_dir = tmp_path / ".remora"
        events_dir = remora_dir / "events"
        events_dir.mkdir(parents=True)
        (events_dir / "events.db").touch()

        mock_store = MagicMock()
        mock_store.initialize = AsyncMock()
        mock_store.list_nodes = AsyncMock(return_value=[])
        mock_store.close = AsyncMock()

        with patch("remora.core.event_store.EventStore", return_value=mock_store):
            result = _invoke("swarm", "list", "--project-root", str(tmp_path))

        assert result.exit_code == 0
        assert "No agents found" in result.output

    def test_with_agents(self, tmp_path: Path):
        """When agents exist, lists them."""
        remora_dir = tmp_path / ".remora"
        events_dir = remora_dir / "events"
        events_dir.mkdir(parents=True)
        (events_dir / "events.db").touch()

        agent = MagicMock()
        agent.node_id = "rm_abc123def456xyz9"
        agent.node_type = "function"
        agent.file_path = "src/mod.py"
        agent.status = "idle"

        mock_store = MagicMock()
        mock_store.initialize = AsyncMock()
        mock_store.list_nodes = AsyncMock(return_value=[agent])
        mock_store.close = AsyncMock()

        with patch("remora.core.event_store.EventStore", return_value=mock_store):
            result = _invoke("swarm", "list", "--project-root", str(tmp_path))

        assert result.exit_code == 0
        assert "Agents (1)" in result.output
        assert "function" in result.output
        assert "src/mod.py" in result.output
        assert "idle" in result.output


# =========================================================================
# 2. swarm emit
# =========================================================================


class TestSwarmEmit:
    """Tests for `remora swarm emit`."""

    def test_agent_message_event(self, tmp_path: Path):
        """Emit AgentMessageEvent with valid JSON data."""
        mock_store = MagicMock()
        mock_store.initialize = AsyncMock()
        mock_store.append = AsyncMock(return_value="evt_001")
        mock_store.close = AsyncMock()

        data = json.dumps({"from_agent": "cli", "to_agent": "rm_abc", "content": "hello"})

        with patch("remora.core.event_store.EventStore", return_value=mock_store):
            result = _invoke(
                "swarm",
                "emit",
                "AgentMessageEvent",
                data,
                "--project-root",
                str(tmp_path),
            )

        assert result.exit_code == 0
        assert "Event emitted" in result.output
        assert "AgentMessageEvent" in result.output

    def test_content_changed_event(self, tmp_path: Path):
        """Emit ContentChangedEvent with valid JSON data."""
        mock_store = MagicMock()
        mock_store.initialize = AsyncMock()
        mock_store.append = AsyncMock(return_value="evt_002")
        mock_store.close = AsyncMock()

        data = json.dumps({"path": "src/foo.py", "diff": "+new line"})

        with patch("remora.core.event_store.EventStore", return_value=mock_store):
            result = _invoke(
                "swarm",
                "emit",
                "ContentChangedEvent",
                data,
                "--project-root",
                str(tmp_path),
            )

        assert result.exit_code == 0
        assert "Event emitted" in result.output
        assert "ContentChangedEvent" in result.output

    def test_invalid_json_data(self, tmp_path: Path):
        """Invalid JSON in data argument raises ClickException."""
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["swarm", "emit", "AgentMessageEvent", "not-valid-json", "--project-root", str(tmp_path)],
        )
        assert result.exit_code != 0
        assert "valid JSON" in result.output

    def test_unknown_event_type(self, tmp_path: Path):
        """Unknown event type raises ClickException."""
        mock_store = MagicMock()
        mock_store.initialize = AsyncMock()
        mock_store.close = AsyncMock()

        with patch("remora.core.event_store.EventStore", return_value=mock_store):
            runner = CliRunner()
            result = runner.invoke(
                main,
                ["swarm", "emit", "UnknownEvent", "{}", "--project-root", str(tmp_path)],
            )

        assert result.exit_code != 0
        assert "Unknown event type" in result.output

    def test_emit_no_data(self, tmp_path: Path):
        """Emit event with no data argument (default empty dict)."""
        mock_store = MagicMock()
        mock_store.initialize = AsyncMock()
        mock_store.append = AsyncMock(return_value="evt_003")
        mock_store.close = AsyncMock()

        with patch("remora.core.event_store.EventStore", return_value=mock_store):
            result = _invoke(
                "swarm",
                "emit",
                "AgentMessageEvent",
                "--project-root",
                str(tmp_path),
            )

        assert result.exit_code == 0
        assert "Event emitted" in result.output


# =========================================================================
# 3. swarm reconcile
# =========================================================================


class TestSwarmReconcile:
    """Tests for `remora swarm reconcile`."""

    def test_reconcile_success(self, tmp_path: Path):
        """Successful reconciliation prints stats."""
        mock_subs = MagicMock()
        mock_subs.initialize = AsyncMock()
        mock_subs.close = AsyncMock()

        mock_store = MagicMock()
        mock_store.initialize = AsyncMock()
        mock_store.close = AsyncMock()

        recon_result = {"created": 5, "orphaned": 1, "total": 10}
        mock_reconcile = AsyncMock(return_value=recon_result)

        with (
            patch("remora.core.subscriptions.SubscriptionRegistry", return_value=mock_subs),
            patch("remora.core.event_store.EventStore", return_value=mock_store),
            patch("remora.core.reconciler.reconcile_on_startup", mock_reconcile),
        ):
            result = _invoke(
                "swarm",
                "reconcile",
                "--project-root",
                str(tmp_path),
            )

        assert result.exit_code == 0
        assert "Created: 5" in result.output
        assert "Orphaned: 1" in result.output
        assert "Total: 10" in result.output

    def test_reconcile_config_error(self, tmp_path: Path):
        """Config error produces a ClickException."""
        with patch("remora.cli.main.load_config", side_effect=ConfigError("bad config")):
            runner = CliRunner()
            result = runner.invoke(
                main,
                ["swarm", "reconcile", "--project-root", str(tmp_path)],
            )

        assert result.exit_code != 0
        assert "bad config" in result.output


# =========================================================================
# 4. swarm start
# =========================================================================


class TestSwarmStart:
    """Tests for `remora swarm start`."""

    def test_start_config_error(self, tmp_path: Path):
        """Config error produces ClickException."""
        with patch("remora.cli.main.load_config", side_effect=ConfigError("missing file")):
            runner = CliRunner()
            result = runner.invoke(
                main,
                ["swarm", "start", "--project-root", str(tmp_path)],
            )

        assert result.exit_code != 0
        assert "missing file" in result.output

    def test_start_headless_reconciles(self, tmp_path: Path):
        """Headless start reconciles and creates runner."""
        mock_subs = MagicMock()
        mock_subs.initialize = AsyncMock()

        mock_store = MagicMock()
        mock_store.initialize = AsyncMock()
        mock_store.set_subscriptions = MagicMock()
        mock_store.set_event_bus = MagicMock()

        mock_bus = MagicMock()

        recon_result = {"created": 3, "orphaned": 0, "total": 8}
        mock_reconcile = AsyncMock(return_value=recon_result)

        mock_runner = MagicMock()
        mock_runner._running = False
        mock_runner.run_forever = AsyncMock()
        mock_runner.run_from_event_store = AsyncMock()
        mock_runner.stop = MagicMock()

        # We need to simulate Ctrl+C (KeyboardInterrupt) to exit the event loop
        # The _start function waits on asyncio.Event().wait(), which blocks forever.
        # We'll raise CancelledError to break out.
        original_event = MagicMock()
        original_event.wait = AsyncMock(side_effect=asyncio.CancelledError)

        with (
            patch("remora.core.subscriptions.SubscriptionRegistry", return_value=mock_subs),
            patch("remora.core.event_store.EventStore", return_value=mock_store),
            patch("remora.core.event_bus.EventBus", return_value=mock_bus),
            patch("remora.core.reconciler.reconcile_on_startup", mock_reconcile),
            patch("remora.runner.agent_runner.AgentRunner.create_headless", return_value=mock_runner),
            patch("asyncio.Event", return_value=original_event),
        ):
            result = _invoke(
                "swarm",
                "start",
                "--project-root",
                str(tmp_path),
            )

        assert result.exit_code == 0
        assert "Reconciling swarm" in result.output
        assert "Swarm reconciled" in result.output
        mock_reconcile.assert_called_once()

    def test_start_lsp_mode(self, tmp_path: Path):
        """LSP mode reconciles then delegates to lsp_main."""
        mock_subs = MagicMock()
        mock_subs.initialize = AsyncMock()

        mock_store = MagicMock()
        mock_store.initialize = AsyncMock()
        mock_store.set_subscriptions = MagicMock()
        mock_store.set_event_bus = MagicMock()

        mock_bus = MagicMock()

        recon_result = {"created": 0, "orphaned": 0, "total": 5}
        mock_reconcile = AsyncMock(return_value=recon_result)

        mock_lsp_main = MagicMock()

        with (
            patch("remora.core.subscriptions.SubscriptionRegistry", return_value=mock_subs),
            patch("remora.core.event_store.EventStore", return_value=mock_store),
            patch("remora.core.event_bus.EventBus", return_value=mock_bus),
            patch("remora.core.reconciler.reconcile_on_startup", mock_reconcile),
            patch("remora.lsp.__main__.main", mock_lsp_main),
        ):
            result = _invoke(
                "swarm",
                "start",
                "--lsp",
                "--project-root",
                str(tmp_path),
            )

        assert result.exit_code == 0
        assert "Reconciling swarm" in result.output
        mock_lsp_main.assert_called_once()
        # Verify it was called with the expected keyword args
        call_kwargs = mock_lsp_main.call_args[1]
        assert "event_store" in call_kwargs
        assert "subscriptions" in call_kwargs


# =========================================================================
# 5. serve
# =========================================================================


class TestServe:
    """Tests for `remora serve`."""

    def test_serve_config_error(self, tmp_path: Path):
        """Config error produces ClickException."""
        with patch("remora.cli.main.load_config", side_effect=ConfigError("bad yaml")):
            runner = CliRunner()
            result = runner.invoke(
                main,
                ["serve", "--project-root", str(tmp_path)],
            )

        assert result.exit_code != 0
        assert "bad yaml" in result.output

    def test_serve_creates_app_and_runs(self, tmp_path: Path):
        """serve creates app via create_app and runs uvicorn."""
        mock_app = MagicMock()
        mock_service = MagicMock()

        with (
            patch("remora.cli.main.load_config", return_value=MagicMock()),
            patch("remora.cli.main.RemoraService.create_default", return_value=mock_service),
            patch("remora.cli.main.create_app", return_value=mock_app) as mock_create_app,
            patch("uvicorn.run") as mock_uvicorn,
        ):
            result = _invoke(
                "serve",
                "--host",
                "127.0.0.1",
                "--port",
                "9000",
                "--project-root",
                str(tmp_path),
            )

        assert result.exit_code == 0
        mock_create_app.assert_called_once_with(mock_service)
        mock_uvicorn.assert_called_once_with(mock_app, host="127.0.0.1", port=9000)

    def test_serve_default_host_port(self, tmp_path: Path):
        """serve uses default host 0.0.0.0 and port 8420."""
        mock_app = MagicMock()

        with (
            patch("remora.cli.main.load_config", return_value=MagicMock()),
            patch("remora.cli.main.RemoraService.create_default", return_value=MagicMock()),
            patch("remora.cli.main.create_app", return_value=mock_app),
            patch("uvicorn.run") as mock_uvicorn,
        ):
            result = _invoke(
                "serve",
                "--project-root",
                str(tmp_path),
            )

        assert result.exit_code == 0
        mock_uvicorn.assert_called_once_with(mock_app, host="0.0.0.0", port=8420)


# =========================================================================
# 6. main group
# =========================================================================


class TestMainGroup:
    """Tests for the root CLI group."""

    def test_help(self):
        """--help shows usage info."""
        result = _invoke("--help")
        assert result.exit_code == 0
        assert "Remora" in result.output

    def test_swarm_help(self):
        """swarm --help shows swarm subcommands."""
        result = _invoke("swarm", "--help")
        assert result.exit_code == 0
        assert "start" in result.output
        assert "list" in result.output
        assert "reconcile" in result.output
        assert "emit" in result.output
