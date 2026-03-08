from __future__ import annotations

import inspect

import remora.lsp.__main__ as entrypoint


def test_main_prepare_initializes_event_store() -> None:
    source = inspect.getsource(entrypoint.main)
    assert "await event_store.initialize()" in source
