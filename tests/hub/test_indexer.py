from __future__ import annotations

from pathlib import Path

import pytest

from remora.hub.indexer import index_file_simple


class FakeStore:
    def __init__(self) -> None:
        self.invalidated: str | None = None
        self.states = []
        self.file_index = None

    async def invalidate_file(self, file_path: str):
        self.invalidated = file_path
        return []

    async def set(self, state):
        self.states.append(state)

    async def set_many(self, states):
        self.states.extend(states)

    async def set_file_index(self, index):
        self.file_index = index


@pytest.mark.asyncio
async def test_index_file_simple_extracts_nodes(tmp_path: Path) -> None:
    content = """
@decorator
async def greet(name: str) -> str:
    \"\"\"Greet someone.\nExtra line.\"\"\"
    return name

class Widget(Base):
    \"\"\"Widget docs.\"\"\"
    pass
"""
    file_path = tmp_path / "sample.py"
    file_path.write_text(content, encoding="utf-8")

    store = FakeStore()
    count = await index_file_simple(file_path, store)

    assert count == 2
    assert store.invalidated == str(file_path)
    assert store.file_index.file_path == str(file_path)

    function_state = next(state for state in store.states if state.node_type == "function")
    assert function_state.signature.startswith("async def greet")
    assert function_state.docstring == "Greet someone."
    assert "@decorator" in function_state.decorators
    assert function_state.has_type_hints is True

    class_state = next(state for state in store.states if state.node_type == "class")
    assert class_state.signature == "class Widget(Base)"
    assert class_state.docstring == "Widget docs."
