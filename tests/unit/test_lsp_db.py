# tests/unit/test_lsp_db.py
from __future__ import annotations

import pytest
from pathlib import Path
import tempfile

from remora.lsp.db import RemoraDB
from remora.lsp.models import ASTAgentNode


@pytest.fixture
async def db(tmp_path):
    db = RemoraDB(str(tmp_path / "test.db"))
    yield db
    db.close()


@pytest.mark.asyncio
async def test_upsert_and_get_node(db):
    node = ASTAgentNode(
        remora_id="rm_test1234",
        node_type="function",
        name="my_func",
        file_path="file:///test.py",
        start_line=1,
        end_line=10,
        source_code="def my_func(): pass",
        source_hash="abc123",
    )
    await db.upsert_nodes([node])
    result = await db.get_node("rm_test1234")
    assert result is not None
    assert result["name"] == "my_func"


@pytest.mark.asyncio
async def test_get_nodes_for_file(db):
    nodes = [
        ASTAgentNode(
            remora_id=f"rm_test000{i}",
            node_type="function",
            name=f"func_{i}",
            file_path="file:///test.py",
            start_line=i * 10,
            end_line=i * 10 + 5,
            source_code=f"def func_{i}(): pass",
            source_hash=f"hash{i}",
        )
        for i in range(3)
    ]
    await db.upsert_nodes(nodes)
    results = await db.get_nodes_for_file("file:///test.py")
    assert len(results) == 3
