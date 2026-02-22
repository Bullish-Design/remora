from __future__ import annotations

from click.testing import CliRunner
import pytest

from remora.hub import cli as hub_cli


def test_status_not_initialized(tmp_path) -> None:
    runner = CliRunner()

    result = runner.invoke(hub_cli.cli, ["status", "--project-root", str(tmp_path)])

    assert result.exit_code == 0
    assert "not initialized" in result.output


def test_stop_without_pid_file(tmp_path) -> None:
    runner = CliRunner()

    result = runner.invoke(hub_cli.cli, ["stop", "--project-root", str(tmp_path)])

    assert result.exit_code == 0
    assert "not running" in result.output


def test_daemonize_non_posix(monkeypatch) -> None:
    monkeypatch.setattr(hub_cli.os, "name", "nt")

    with pytest.raises(hub_cli.click.ClickException):
        hub_cli._daemonize()


def test_start_invokes_asyncio_run(monkeypatch, tmp_path) -> None:
    called = {"ran": False}

    class FakeDaemon:
        def __init__(self, project_root, db_path) -> None:
            self.project_root = project_root
            self.db_path = db_path

        async def run(self):
            return None

    def fake_run(coro):
        called["ran"] = True
        coro.close()

    monkeypatch.setattr(hub_cli, "HubDaemon", FakeDaemon)
    monkeypatch.setattr(hub_cli.asyncio, "run", fake_run)

    hub_cli.start.callback(project_root=tmp_path, db_path=None, log_level="INFO", foreground=True)

    assert called["ran"]
