"""Integration tests for Hub daemon and client."""

from __future__ import annotations

import asyncio
import ast
import hashlib
import textwrap
from contextlib import suppress
from pathlib import Path
from typing import Any

import pytest

from remora.context.hub_client import HubClient
from remora.hub.daemon import HubDaemon
from remora.hub.models import NodeState


async def _wait_for_context(client: HubClient, node_id: str) -> dict[str, NodeState]:
    for _ in range(50):
        context = await client.get_context([node_id])
        if context:
            return context
        await asyncio.sleep(0.1)
    return {}


class SimpleGrailExecutor:
    async def run(
        self,
        script_path: str,
        inputs: dict[str, Any],
        externals: dict[str, Any],
    ) -> dict[str, Any]:
        file_path = Path(inputs["file_path"])
        content = await externals["read_file"](str(file_path))
        file_hash = hashlib.sha256(content.encode()).hexdigest()

        try:
            tree = ast.parse(content)
        except SyntaxError as exc:
            return {
                "file_path": str(file_path),
                "file_hash": file_hash,
                "error": f"Syntax error at line {exc.lineno}: {exc.msg}",
                "nodes": [],
            }

        nodes: list[dict[str, Any]] = []
        lines = content.splitlines()

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                nodes.append(_extract_function(node, lines, is_async=False))
            elif isinstance(node, ast.AsyncFunctionDef):
                nodes.append(_extract_function(node, lines, is_async=True))
            elif isinstance(node, ast.ClassDef):
                nodes.append(_extract_class(node, lines))

        return {
            "file_path": str(file_path),
            "file_hash": file_hash,
            "nodes": nodes,
            "error": None,
        }


def _extract_function(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    lines: list[str],
    is_async: bool,
) -> dict[str, Any]:
    start = node.lineno - 1
    end = node.end_lineno or start + 1
    func_source = "\n".join(lines[start:end])
    source_hash = hashlib.sha256(func_source.encode()).hexdigest()

    args = []
    for arg in node.args.args:
        arg_str = arg.arg
        if arg.annotation:
            arg_str += f": {ast.unparse(arg.annotation)}"
        args.append(arg_str)

    if node.args.vararg:
        vararg = f"*{node.args.vararg.arg}"
        if node.args.vararg.annotation:
            vararg += f": {ast.unparse(node.args.vararg.annotation)}"
        args.append(vararg)

    if node.args.kwarg:
        kwarg = f"**{node.args.kwarg.arg}"
        if node.args.kwarg.annotation:
            kwarg += f": {ast.unparse(node.args.kwarg.annotation)}"
        args.append(kwarg)

    returns = ""
    if node.returns:
        returns = f" -> {ast.unparse(node.returns)}"

    prefix = "async def" if is_async else "def"
    signature = f"{prefix} {node.name}({', '.join(args)}){returns}"

    docstring = ast.get_docstring(node)
    if docstring:
        docstring = docstring.split("\n")[0][:100]

    decorators = [f"@{ast.unparse(d)}" for d in node.decorator_list]

    has_type_hints = node.returns is not None or any(a.annotation for a in node.args.args)

    return {
        "name": node.name,
        "type": "function",
        "signature": signature,
        "docstring": docstring,
        "decorators": decorators,
        "source_hash": source_hash,
        "line_count": end - start,
        "has_type_hints": has_type_hints,
        "start_line": node.lineno,
        "end_line": end,
    }


def _extract_class(node: ast.ClassDef, lines: list[str]) -> dict[str, Any]:
    start = node.lineno - 1
    end = node.end_lineno or start + 1
    class_source = "\n".join(lines[start:end])
    source_hash = hashlib.sha256(class_source.encode()).hexdigest()

    bases = [ast.unparse(base) for base in node.bases]
    signature = f"class {node.name}"
    if bases:
        signature += f"({', '.join(bases)})"

    docstring = ast.get_docstring(node)
    if docstring:
        docstring = docstring.split("\n")[0][:100]

    decorators = [f"@{ast.unparse(d)}" for d in node.decorator_list]

    return {
        "name": node.name,
        "type": "class",
        "signature": signature,
        "docstring": docstring,
        "decorators": decorators,
        "source_hash": source_hash,
        "line_count": end - start,
        "has_type_hints": True,
        "start_line": node.lineno,
        "end_line": end,
    }


@pytest.mark.asyncio
async def test_end_to_end_indexing(tmp_path: Path) -> None:
    test_file = tmp_path / "test_module.py"
    content = textwrap.dedent(
        '''
        """Module docstring."""

        def hello(name: str) -> str:
            """Greet someone."""
            return f"Hello, {name}"
        '''
    ).strip()
    test_file.write_text(content + "\n", encoding="utf-8")

    daemon = HubDaemon(project_root=tmp_path, grail_executor=SimpleGrailExecutor())
    daemon_task = asyncio.create_task(daemon.run())

    client = HubClient(
        hub_db_path=tmp_path / ".remora" / "hub.db",
        project_root=tmp_path,
    )

    try:
        node_id = f"node:{test_file}:hello"
        context = await _wait_for_context(client, node_id)

        assert node_id in context
        node = context[node_id]
        assert node.signature == "def hello(name: str) -> str"
        assert node.docstring == "Greet someone."
    finally:
        if daemon.watcher is not None:
            daemon.watcher.stop()
        daemon_task.cancel()
        with suppress(asyncio.CancelledError):
            await daemon_task
        await client.close()
