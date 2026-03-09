from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from remora.lsp.handlers import documents


@pytest.mark.asyncio
async def test_did_open_starts_bootstrap_file_activation_task(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(documents, "parse_content", lambda _uri, _text: [])
    monkeypatch.setattr(documents, "_emit_node_events", AsyncMock())

    bootstrap_runner = SimpleNamespace(run_for_file=AsyncMock(return_value=2))
    ls = SimpleNamespace(
        db=SimpleNamespace(
            update_edges=AsyncMock(),
            get_proposals_for_file=AsyncMock(return_value=[]),
        ),
        refresh_code_lenses=AsyncMock(),
        publish_diagnostics=AsyncMock(),
        notify_agents_updated=AsyncMock(),
        proposals={},
        event_store=None,
        bootstrap_runner=bootstrap_runner,
    )

    params = SimpleNamespace(
        text_document=SimpleNamespace(
            uri="file:///repo/src/app.py",
            text="def app():\n    return 1\n",
        )
    )
    await documents.did_open(ls, params)

    for _ in range(5):
        if bootstrap_runner.run_for_file.await_count:
            break
        await asyncio.sleep(0)

    bootstrap_runner.run_for_file.assert_awaited_once_with("file:///repo/src/app.py")
