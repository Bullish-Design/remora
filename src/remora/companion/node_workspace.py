"""Node workspace layout conventions and helpers.

Every NodeAgent has a Cairn AgentWorkspace keyed by node_id.
All paths within that workspace follow the conventions defined here.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from remora.core.agents.workspace import AgentWorkspace

META = "meta.json"
USER_NOTES = "notes/user_notes.md"
AGENT_NOTES = "notes/agent_notes.md"
CHAT_INDEX = "chat/index.json"
LINKS = "links/links.json"
CONTEXT_LATEST = "context/latest_extraction.json"
SOURCE_SNAPSHOT = "context/source_snapshot.md"


@dataclass
class ChatIndexEntry:
    session_id: str
    timestamp: float
    summary: str
    tags: list[str] = field(default_factory=list)
    turn_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "summary": self.summary,
            "tags": self.tags,
            "turn_count": self.turn_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ChatIndexEntry":
        return cls(
            session_id=data["session_id"],
            timestamp=data.get("timestamp", 0.0),
            summary=data.get("summary", ""),
            tags=data.get("tags", []),
            turn_count=data.get("turn_count", 0),
        )


@dataclass
class NodeMeta:
    node_id: str
    node_type: str
    name: str
    file_path: str
    first_seen: float = field(default_factory=time.time)
    last_visited: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "node_type": self.node_type,
            "name": self.name,
            "file_path": self.file_path,
            "first_seen": self.first_seen,
            "last_visited": self.last_visited,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NodeMeta":
        return cls(**data)


async def read_json(workspace: AgentWorkspace, path: str) -> Any:
    """Read and parse a JSON file from the workspace. Returns None if missing."""
    try:
        text = await workspace.read(path)
        return json.loads(text)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


async def write_json(workspace: AgentWorkspace, path: str, data: Any) -> None:
    """Serialize data to JSON and write to workspace."""
    await workspace.write(path, json.dumps(data, indent=2))


async def read_text(workspace: AgentWorkspace, path: str, default: str = "") -> str:
    """Read a text file from the workspace. Returns default if missing."""
    try:
        return await workspace.read(path)
    except FileNotFoundError:
        return default


async def write_text(workspace: AgentWorkspace, path: str, content: str) -> None:
    """Write text content to a workspace file."""
    await workspace.write(path, content)


async def append_text(workspace: AgentWorkspace, path: str, content: str) -> None:
    """Append content to a text file in the workspace."""
    existing = await read_text(workspace, path)
    await workspace.write(path, existing + content)


async def load_chat_index(workspace: AgentWorkspace) -> list[ChatIndexEntry]:
    """Load the chat session index from workspace."""
    raw = await read_json(workspace, CHAT_INDEX)
    if not raw:
        return []
    return [ChatIndexEntry.from_dict(entry) for entry in raw]


async def save_chat_index(workspace: AgentWorkspace, index: list[ChatIndexEntry]) -> None:
    """Save the chat session index to workspace."""
    await write_json(workspace, CHAT_INDEX, [entry.to_dict() for entry in index])


async def ensure_meta(
    workspace: AgentWorkspace,
    node_id: str,
    node_type: str,
    name: str,
    file_path: str,
) -> NodeMeta:
    """Create or load node metadata. Updates last_visited on each call."""
    raw = await read_json(workspace, META)
    if raw:
        meta = NodeMeta.from_dict(raw)
        meta.last_visited = time.time()
    else:
        meta = NodeMeta(node_id=node_id, node_type=node_type, name=name, file_path=file_path)
    await write_json(workspace, META, meta.to_dict())
    return meta


__all__ = [
    "META",
    "USER_NOTES",
    "AGENT_NOTES",
    "CHAT_INDEX",
    "LINKS",
    "CONTEXT_LATEST",
    "SOURCE_SNAPSHOT",
    "ChatIndexEntry",
    "NodeMeta",
    "read_json",
    "write_json",
    "read_text",
    "write_text",
    "append_text",
    "load_chat_index",
    "save_chat_index",
    "ensure_meta",
]
