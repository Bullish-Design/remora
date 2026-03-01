from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from lsprotocol import types as lsp

import importlib

from remora.cli.main import swarm_start
from remora.lsp.server import server

pytestmark = pytest.mark.integration


def test_lsp_handlers_register_and_advertise_capabilities() -> None:
    """Ensure the LSP handlers register and declare execute-command options."""

    feature_names = set(server.protocol.fm.features.keys())
    expected = {
        "textDocument/didOpen",
        "textDocument/didSave",
        "textDocument/didClose",
        "textDocument/hover",
        "textDocument/codeLens",
        "textDocument/codeAction",
        "textDocument/documentSymbol",
        "workspace/executeCommand",
        "initialize",
        "$/remora/submitInput",
    }
    missing = expected - feature_names
    assert not missing, f"Expected features missing: {sorted(missing)}"

    # Fire the initialize handler to populate executeCommand options
    if not hasattr(server.protocol, "server_capabilities"):
        import types

        server.protocol.server_capabilities = types.SimpleNamespace()

    init_handler = server.protocol.fm.features["initialize"]
    asyncio.run(
        init_handler(
            lsp.InitializeParams(process_id=None, root_uri=None, capabilities=lsp.ClientCapabilities())
        )
    )

    commands = server.protocol.server_capabilities.execute_command_provider
    assert commands is not None
    assert "remora.chat" in commands.commands
    assert "remora.acceptProposal" in commands.commands


def test_cli_swarm_start_lsp_initializes_services(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`remora swarm start --lsp` should pass the prepared services into the LSP server."""

    dummy_store = object()
    dummy_subscriptions = object()
    dummy_state = object()
    run_called: dict[str, bool] = {}
    lsp_called: dict[str, tuple] = {}

    def fake_run(coro):
        run_called["called"] = True
        try:
            coro.close()
        except Exception:
            pass
        return dummy_store, dummy_subscriptions, dummy_state

    def stub(event_store=None, subscriptions=None, swarm_state=None) -> None:
        lsp_called["args"] = (event_store, subscriptions, swarm_state)

    monkeypatch.setattr("remora.lsp.__main__.main", stub)
    cli_module = importlib.import_module("remora.cli.main")
    monkeypatch.setattr(cli_module.asyncio, "run", fake_run)

    project_root = tmp_path / "project"
    project_root.mkdir()
    config_path = project_root / "remora.yaml"
    config_path.write_text("", encoding="utf-8")

    swarm_start.callback(str(project_root), str(config_path), False, True)

    assert run_called.get("called"), "asyncio.run was not invoked"
    assert "args" in lsp_called
    event_store, subscriptions, swarm_state = lsp_called["args"]
    assert event_store is dummy_store
    assert subscriptions is dummy_subscriptions
    assert swarm_state is dummy_state
