"""CST node discovery utilities for Remora."""

from __future__ import annotations

from dataclasses import dataclass
import ast
import hashlib
from pathlib import Path
from typing import Iterable, Literal

from pydantic import BaseModel

from remora.errors import DISC_001, DISC_002


class DiscoveryError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class CSTNode(BaseModel):
    node_id: str
    node_type: Literal["file", "class", "function"]
    name: str
    file_path: Path
    start_byte: int
    end_byte: int
    text: str


@dataclass
class NodeDiscoverer:
    root_dirs: list[Path]
    query_names: list[str]
    queries_dir: Path = Path(__file__).parent / "queries"

    def __init__(
        self,
        root_dirs: Iterable[Path],
        query_names: Iterable[str],
        queries_dir: Path | None = None,
    ) -> None:
        self.root_dirs = [Path(path) for path in root_dirs]
        self.query_names = list(query_names)
        if queries_dir is not None:
            self.queries_dir = queries_dir

    def discover(self) -> list[CSTNode]:
        self._load_queries()
        nodes: list[CSTNode] = []
        for file_path in self._iter_python_files():
            nodes.extend(self._discover_file_nodes(file_path))
        nodes.sort(key=lambda node: (str(node.file_path), node.start_byte, node.node_type, node.name))
        return nodes

    def _load_queries(self) -> None:
        for name in self.query_names:
            query_path = self.queries_dir / f"{name}.scm"
            try:
                content = query_path.read_text(encoding="utf-8")
            except FileNotFoundError as exc:
                raise DiscoveryError(DISC_001, f"Query file not found: {query_path}") from exc
            except OSError as exc:
                raise DiscoveryError(DISC_001, f"Failed to read query file: {query_path}") from exc
            self._validate_query_contents(content, query_path)

    def _validate_query_contents(self, content: str, query_path: Path) -> None:
        stripped = content.strip()
        if not stripped:
            raise DiscoveryError(DISC_002, f"Query file is empty or invalid: {query_path}")
        balance = 0
        in_string = False
        escape_next = False
        for char in content:
            if in_string:
                if escape_next:
                    escape_next = False
                    continue
                if char == "\\":
                    escape_next = True
                    continue
                if char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
                continue
            if char == "(":
                balance += 1
            elif char == ")":
                balance -= 1
                if balance < 0:
                    raise DiscoveryError(DISC_002, f"Malformed query file: {query_path}")
        if in_string or balance != 0:
            raise DiscoveryError(DISC_002, f"Malformed query file: {query_path}")

    def _iter_python_files(self) -> list[Path]:
        files: list[Path] = []
        for root in self.root_dirs:
            if root.is_file() and root.suffix == ".py":
                files.append(root)
            elif root.is_dir():
                files.extend(path for path in root.rglob("*.py") if path.is_file())
        return sorted(files, key=lambda path: str(path))

    def _discover_file_nodes(self, file_path: Path) -> list[CSTNode]:
        source_text = file_path.read_text(encoding="utf-8")
        source_bytes = source_text.encode("utf-8")
        line_offsets, lines = _build_line_offsets(source_text)
        nodes: list[CSTNode] = []

        if "file" in self.query_names:
            nodes.append(
                CSTNode(
                    node_id=_compute_node_id(file_path, "file", file_path.stem),
                    node_type="file",
                    name=file_path.stem,
                    file_path=file_path,
                    start_byte=0,
                    end_byte=len(source_bytes),
                    text=source_text,
                )
            )

        if any(name in self.query_names for name in ("class_def", "function_def")):
            tree = ast.parse(source_text, filename=str(file_path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and "class_def" in self.query_names:
                    nodes.append(
                        self._build_node(
                            file_path,
                            source_bytes,
                            line_offsets,
                            lines,
                            node,
                            "class",
                            node.name,
                        )
                    )
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and "function_def" in self.query_names:
                    nodes.append(
                        self._build_node(
                            file_path,
                            source_bytes,
                            line_offsets,
                            lines,
                            node,
                            "function",
                            node.name,
                        )
                    )
        return nodes

    def _build_node(
        self,
        file_path: Path,
        source_bytes: bytes,
        line_offsets: list[int],
        lines: list[str],
        node: ast.AST,
        node_type: Literal["class", "function"],
        name: str,
    ) -> CSTNode:
        start_line = getattr(node, "lineno", None)
        start_col = getattr(node, "col_offset", None)
        end_line = getattr(node, "end_lineno", None)
        end_col = getattr(node, "end_col_offset", None)
        if None in (start_line, start_col, end_line, end_col):
            raise DiscoveryError(DISC_002, f"Unable to compute node span for {name} in {file_path}")
        assert start_line is not None
        assert start_col is not None
        assert end_line is not None
        assert end_col is not None
        start_byte = _line_col_to_byte(line_offsets, lines, start_line, start_col)
        end_byte = _line_col_to_byte(line_offsets, lines, end_line, end_col)
        text = source_bytes[start_byte:end_byte].decode("utf-8")
        return CSTNode(
            node_id=_compute_node_id(file_path, node_type, name),
            node_type=node_type,
            name=name,
            file_path=file_path,
            start_byte=start_byte,
            end_byte=end_byte,
            text=text,
        )


def _build_line_offsets(source_text: str) -> tuple[list[int], list[str]]:
    lines = source_text.splitlines(keepends=True)
    offsets: list[int] = []
    total = 0
    for line in lines:
        offsets.append(total)
        total += len(line.encode("utf-8"))
    return offsets, lines


def _line_col_to_byte(offsets: list[int], lines: list[str], line: int, col: int) -> int:
    if line < 1 or line > len(lines):
        raise DiscoveryError(DISC_002, f"Invalid line number {line} while computing node span")
    line_text = lines[line - 1]
    return offsets[line - 1] + len(line_text[:col].encode("utf-8"))


def _compute_node_id(file_path: Path, node_type: str, name: str) -> str:
    digest_input = f"{file_path.resolve()}::{node_type}::{name}".encode("utf-8")
    return hashlib.sha1(digest_input).hexdigest()
