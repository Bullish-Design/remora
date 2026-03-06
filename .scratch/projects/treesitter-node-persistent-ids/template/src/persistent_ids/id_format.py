"""Graph ID parsing and encoding helpers."""

from __future__ import annotations

import re
import uuid

_GRAPH_ID_PATTERN = re.compile(r"\bgraph:id=([A-Za-z0-9_-]{8,64})\b")


def parse_graph_id(line: str) -> str | None:
    """Return graph ID from a header line if present."""

    match = _GRAPH_ID_PATTERN.search(line)
    return match.group(1) if match else None


def new_graph_id() -> str:
    """Generate a UUIDv4 graph ID string."""

    return str(uuid.uuid4())


def graph_id_to_bytes(graph_id: str) -> bytes:
    """Encode UUID-form graph ID to 16-byte representation."""

    return uuid.UUID(graph_id).bytes


def graph_id_from_bytes(raw: bytes) -> str:
    """Decode 16-byte UUID data to canonical string form."""

    return str(uuid.UUID(bytes=raw))
