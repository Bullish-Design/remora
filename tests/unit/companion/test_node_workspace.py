"""Tests for node workspace conventions and helpers."""
import pytest
from unittest.mock import MagicMock

from remora.companion.node_workspace import (
    ChatIndexEntry,
    append_text,
    ensure_meta,
    load_chat_index,
    read_json,
    read_text,
    save_chat_index,
    write_json,
)


def make_workspace():
    store: dict[str, str] = {}
    ws = MagicMock()

    async def read(path):
        if path not in store:
            raise FileNotFoundError(path)
        return store[path]

    async def write(path, content):
        store[path] = content if isinstance(content, str) else content.decode()

    ws.read = read
    ws.write = write
    return ws, store


@pytest.mark.asyncio
async def test_read_json_missing_returns_none():
    ws, _ = make_workspace()
    assert await read_json(ws, "missing.json") is None


@pytest.mark.asyncio
async def test_write_read_json_roundtrip():
    ws, _ = make_workspace()
    data = {"key": "value", "nums": [1, 2, 3]}
    await write_json(ws, "test.json", data)
    assert await read_json(ws, "test.json") == data


@pytest.mark.asyncio
async def test_read_text_missing_returns_default():
    ws, _ = make_workspace()
    assert await read_text(ws, "missing.md", default="hello") == "hello"


@pytest.mark.asyncio
async def test_append_text_creates_file():
    ws, _ = make_workspace()
    await append_text(ws, "notes.md", "first line\n")
    await append_text(ws, "notes.md", "second line\n")
    result = await read_text(ws, "notes.md")
    assert "first line" in result
    assert "second line" in result


@pytest.mark.asyncio
async def test_chat_index_roundtrip():
    ws, _ = make_workspace()
    entry = ChatIndexEntry(
        session_id="abc123",
        timestamp=1000.0,
        summary="We discussed the timeout bug.",
        tags=["bug", "debugging"],
        turn_count=3,
    )
    await save_chat_index(ws, [entry])
    loaded = await load_chat_index(ws)
    assert len(loaded) == 1
    assert loaded[0].session_id == "abc123"
    assert loaded[0].summary == "We discussed the timeout bug."
    assert "bug" in loaded[0].tags


@pytest.mark.asyncio
async def test_ensure_meta_creates_on_first_call():
    ws, _ = make_workspace()
    meta = await ensure_meta(ws, "node_abc", "function", "my_func", "foo.py")
    assert meta.node_id == "node_abc"
    assert meta.node_type == "function"
    assert meta.name == "my_func"


@pytest.mark.asyncio
async def test_ensure_meta_updates_last_visited():
    ws, _ = make_workspace()
    meta1 = await ensure_meta(ws, "node_abc", "function", "my_func", "foo.py")
    import time

    time.sleep(0.01)
    meta2 = await ensure_meta(ws, "node_abc", "function", "my_func", "foo.py")
    assert meta2.last_visited >= meta1.last_visited
