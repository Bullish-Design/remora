from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from lsprotocol import types as lsp

from remora.lsp.handlers import actions, capabilities, commands, documents, lens
from remora.lsp.server import server
from remora.lsp.db import RemoraDB
from remora.lsp.graph import LazyGraph
from remora.lsp.watcher import ASTWatcher
from remora.core.event_store import EventStore
from remora.core.projections import NodeProjection

pytestmark = pytest.mark.integration


def _cli_env(repo_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{repo_root / 'src'}{os.pathsep}{env.get('PYTHONPATH', '')}"
    return env


@pytest.fixture
async def isolated_lsp_server(tmp_path: Path) -> None:
    """Rebuild the shared LSP server to operate inside a scratch directory."""

    server.shutdown()
    server.db = RemoraDB(str(tmp_path / "indexer.db"))
    server.proposals.clear()
    server.watcher = ASTWatcher()
    server._injecting.clear()

    # Set up EventStore with NodeProjection
    event_store = EventStore(
        tmp_path / "events.db",
        projection=NodeProjection(),
    )
    await event_store.initialize()
    server.event_store = event_store
    server.graph = LazyGraph(server.db, event_store_db_path=str(tmp_path / "events.db"))

    original_discover = server.discover_tools_for_agent

    async def _stub_discover(_: object) -> list[object]:
        return []

    server.discover_tools_for_agent = _stub_discover

    yield

    server.shutdown()
    await event_store.close()
    server.discover_tools_for_agent = original_discover


@pytest.mark.asyncio
async def test_lsp_handlers_register_and_advertise_capabilities(isolated_lsp_server) -> None:
    fm = server.protocol.fm
    feature_names = set(fm.features.keys())
    expected_features = {
        "textDocument/didOpen",
        "textDocument/didSave",
        "textDocument/didChange",
        "textDocument/didClose",
        "textDocument/hover",
        "textDocument/codeLens",
        "textDocument/codeAction",
        "textDocument/documentSymbol",
        "initialize",
        "$/remora/submitInput",
    }
    missing = expected_features - feature_names
    assert not missing, f"Expected features missing: {sorted(missing)}"

    # workspace/executeCommand is a pygls builtin, registered automatically
    # when @server.command() decorators are used
    assert "workspace/executeCommand" in fm.builtin_features, (
        "workspace/executeCommand not in builtin_features — commands module not imported?"
    )

    # Verify that the key commands are registered in the feature manager
    registered_commands = set(fm.commands.keys())
    assert "remora.chat" in registered_commands
    assert "remora.acceptProposal" in registered_commands


@pytest.mark.asyncio
async def test_document_handlers_populate_db_and_code_lenses(tmp_path: Path, isolated_lsp_server) -> None:
    source = "def foo():\n    return 1\n"
    uri = f"file://{tmp_path / 'test.py'}"
    params = lsp.DidOpenTextDocumentParams(
        text_document=lsp.TextDocumentItem(
            uri=uri,
            language_id="python",
            version=1,
            text=source,
        )
    )

    await documents.did_open(params)

    # Nodes now live in EventStore, not RemoraDB
    nodes = await server.event_store.list_nodes(file_path=uri)
    assert any(node.node_type == "function" for node in nodes)

    lens_params = lsp.CodeLensParams(text_document=lsp.TextDocumentIdentifier(uri=uri))
    code_lenses = await lens.code_lens(lens_params)
    assert code_lenses
    assert all(isinstance(cl.command.title, str) for cl in code_lenses)

    action_params = lsp.CodeActionParams(
        text_document=lsp.TextDocumentIdentifier(uri=uri),
        range=lsp.Range(start=lsp.Position(line=0, character=0), end=lsp.Position(line=0, character=2)),
        context=lsp.CodeActionContext(diagnostics=[]),
    )
    actions_result = await actions.code_action(action_params)
    commands = {act.command.command for act in actions_result if act.command}
    assert "remora.chat" in commands
    assert "remora.requestRewrite" in commands


@pytest.mark.asyncio
async def test_did_save_emits_file_saved_and_content_changed_events(tmp_path: Path, isolated_lsp_server) -> None:
    """Workstream A: did_save must emit FileSavedEvent + ContentChangedEvent."""
    source = "def foo():\n    return 1\n"
    uri = f"file://{tmp_path / 'test.py'}"

    # First open the file so nodes exist
    open_params = lsp.DidOpenTextDocumentParams(
        text_document=lsp.TextDocumentItem(
            uri=uri,
            language_id="python",
            version=1,
            text=source,
        )
    )
    await documents.did_open(open_params)

    # Now save it
    save_params = lsp.DidSaveTextDocumentParams(
        text_document=lsp.TextDocumentIdentifier(uri=uri),
        text=source,
    )
    await documents.did_save(save_params)

    # Replay the "files" stream and check for FileSavedEvent + ContentChangedEvent
    events = [record async for record in server.event_store.replay("files")]
    event_types = [e["event_type"] for e in events]
    assert "FileSavedEvent" in event_types, f"Expected FileSavedEvent in {event_types}"
    assert "ContentChangedEvent" in event_types, f"Expected ContentChangedEvent in {event_types}"

    # Check event payloads contain the file path
    file_saved = [e for e in events if e["event_type"] == "FileSavedEvent"][0]
    assert uri in file_saved["payload"]["path"]

    content_changed = [e for e in events if e["event_type"] == "ContentChangedEvent"][0]
    assert uri in content_changed["payload"]["path"]


def test_swarm_start_lsp_smoke(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    project_root = tmp_path / "project"
    project_root.mkdir()
    config_path = project_root / "remora.yaml"
    config_path.write_text("", encoding="utf-8")

    cmd = [
        sys.executable,
        "-m",
        "remora",
        "swarm",
        "start",
        "--project-root",
        str(project_root),
        "--config",
        str(config_path),
        "--lsp",
    ]

    proc = subprocess.Popen(
        cmd,
        cwd=repo_root,
        env=_cli_env(repo_root),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        deadline = time.time() + 30
        events_db = project_root / ".remora" / "events" / "events.db"
        while time.time() < deadline:
            if proc.poll() is not None:
                stdout, stderr = proc.communicate(timeout=1)
                raise AssertionError(f"CLI exited early (code={proc.returncode})\nstdout={stdout}\nstderr={stderr}")
            if events_db.exists():
                break
            time.sleep(0.2)
        else:
            raise AssertionError("Failed to create events.db within timeout")

        # We only require that the event store has been written before we're satisfied.
    finally:
        if proc.poll() is None:
            proc.send_signal(signal.SIGINT)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.terminate()
        proc.communicate(timeout=1)

    assert events_db.exists()
