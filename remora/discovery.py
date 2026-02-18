"""Pydantree-backed node discovery utilities for Remora."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import subprocess
import time
from typing import Any, Iterable, Literal

from pydantic import BaseModel

from remora.errors import DISC_001, DISC_002
from remora.events import EventEmitter


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
class PydantreeDiscoverer:
    root_dirs: list[Path]
    language: str
    query_pack: str
    command: str = "pydantree"
    source: str = "repo"
    event_emitter: EventEmitter | None = None

    def __init__(
        self,
        root_dirs: Iterable[Path],
        language: str,
        query_pack: str,
        *,
        command: str = "pydantree",
        source: str = "repo",
        event_emitter: EventEmitter | None = None,
    ) -> None:
        self.root_dirs = [Path(path).resolve() for path in root_dirs]
        self.language = language
        self.query_pack = query_pack
        self.command = command
        self.source = source
        self.event_emitter = event_emitter

    def discover(self) -> list[CSTNode]:
        start = time.monotonic()
        status = "ok"
        try:
            raw = self._run_query()
            nodes = _parse_pydantree_nodes(raw)
            filtered = [node for node in nodes if self._within_roots(node.file_path)]
            filtered.sort(key=lambda node: (str(node.file_path), node.start_byte, node.node_type, node.name))
            return filtered
        except Exception:
            status = "error"
            raise
        finally:
            if self.event_emitter is not None:
                duration_ms = int((time.monotonic() - start) * 1000)
                self.event_emitter.emit(
                    {
                        "event": "discovery",
                        "phase": "discovery",
                        "status": status,
                        "duration_ms": duration_ms,
                    }
                )

    def _run_query(self) -> dict[str, Any] | list[Any]:
        cmd = [self.command, "run-query", self.language, self.query_pack, self.source, "--json"]
        try:
            completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
        except FileNotFoundError as exc:
            raise DiscoveryError(DISC_001, f"Pydantree CLI not found: {self.command}") from exc
        if completed.returncode != 0:
            stderr = completed.stderr.strip() or completed.stdout.strip()
            raise DiscoveryError(DISC_001, f"Pydantree query failed: {stderr}")
        output = completed.stdout.strip()
        if not output:
            raise DiscoveryError(DISC_001, "Pydantree returned empty output.")
        try:
            return json.loads(output)
        except json.JSONDecodeError as exc:
            raise DiscoveryError(DISC_001, f"Pydantree output is not valid JSON: {exc}") from exc

    def _within_roots(self, file_path: Path) -> bool:
        resolved = file_path.resolve()
        return any(resolved == root or root in resolved.parents for root in self.root_dirs)


def _parse_pydantree_nodes(payload: dict[str, Any] | list[Any]) -> list[CSTNode]:
    items: list[Any]
    if isinstance(payload, dict):
        items = payload.get("nodes") or payload.get("matches") or payload.get("results") or []
    elif isinstance(payload, list):
        items = payload
    else:
        raise DiscoveryError(DISC_002, "Unexpected Pydantree output format.")

    if not isinstance(items, list):
        raise DiscoveryError(DISC_002, "Pydantree results payload is not a list.")

    nodes: list[CSTNode] = []
    source_cache: dict[Path, bytes] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        node_data = _node_from_match(item, source_cache)
        if node_data is not None:
            nodes.append(node_data)
    return nodes


def _node_from_match(item: dict[str, Any], source_cache: dict[Path, bytes]) -> CSTNode | None:
    file_path = _coerce_path(item.get("file") or item.get("path") or item.get("file_path"))
    if file_path is None:
        return None

    node_type = _coerce_node_type(item.get("node_type"))
    name = _coerce_str(item.get("name"))
    start_byte, end_byte = _coerce_span(item)

    captures = item.get("captures") if isinstance(item.get("captures"), list) else []
    if captures:
        capture_info = _extract_capture_info(captures)
        node_type = node_type or capture_info.get("node_type")
        name = name or capture_info.get("name")
        if capture_info.get("start_byte") is not None and capture_info.get("end_byte") is not None:
            start_byte = capture_info["start_byte"]
            end_byte = capture_info["end_byte"]

    if node_type is None:
        node_type = "function"
    if name is None:
        name = file_path.stem if node_type == "file" else "unknown"

    if start_byte is None or end_byte is None:
        raise DiscoveryError(DISC_002, f"Missing span for {file_path}")

    source_bytes = _load_source_bytes(file_path, source_cache)
    text = source_bytes[start_byte:end_byte].decode("utf-8", errors="replace")

    return CSTNode(
        node_id=_compute_node_id(file_path, node_type, name),
        node_type=node_type,
        name=name,
        file_path=file_path,
        start_byte=start_byte,
        end_byte=end_byte,
        text=text,
    )


def _extract_capture_info(captures: list[Any]) -> dict[str, Any]:
    info: dict[str, Any] = {}
    for capture in captures:
        if not isinstance(capture, dict):
            continue
        capture_name = _coerce_str(capture.get("name"))
        if not capture_name:
            continue
        if capture_name.endswith(".name"):
            info["name"] = _coerce_str(capture.get("text")) or info.get("name")
            info["node_type"] = _coerce_node_type(capture_name.split(".")[0]) or info.get("node_type")
        if capture_name.endswith(".def"):
            info["node_type"] = _coerce_node_type(capture_name.split(".")[0]) or info.get("node_type")
            info["start_byte"] = capture.get("start_byte")
            info["end_byte"] = capture.get("end_byte")
    return info


def _coerce_span(item: dict[str, Any]) -> tuple[int | None, int | None]:
    start = item.get("start_byte")
    end = item.get("end_byte")
    if isinstance(start, int) and isinstance(end, int):
        return start, end
    return None, None


def _coerce_path(value: Any) -> Path | None:
    if isinstance(value, str) and value:
        return Path(value)
    return None


def _coerce_str(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _coerce_node_type(value: Any) -> Literal["file", "class", "function"] | None:
    if not isinstance(value, str):
        return None
    lowered = value.lower()
    if lowered == "file":
        return "file"
    if lowered == "class":
        return "class"
    if lowered == "function":
        return "function"
    return None


def _load_source_bytes(file_path: Path, cache: dict[Path, bytes]) -> bytes:
    resolved = file_path.resolve()
    if resolved not in cache:
        try:
            cache[resolved] = resolved.read_bytes()
        except OSError as exc:
            raise DiscoveryError(DISC_002, f"Failed to read source file: {resolved}") from exc
    return cache[resolved]


def _compute_node_id(file_path: Path, node_type: str, name: str) -> str:
    digest_input = f"{file_path.resolve()}::{node_type}::{name}".encode("utf-8")
    return hashlib.sha1(digest_input).hexdigest()
