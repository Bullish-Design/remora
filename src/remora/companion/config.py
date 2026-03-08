"""Configuration for the companion node-agent system."""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from embeddy.config import ChunkConfig, EmbedderConfig, StoreConfig


class IndexingConfig(BaseModel):
    """Vector search configuration (wraps embeddy)."""

    embedder: EmbedderConfig = Field(
        default_factory=lambda: EmbedderConfig(mode="remote", remote_url="http://localhost:8586")
    )
    store: StoreConfig = Field(default_factory=lambda: StoreConfig(db_path=".companion/vectors.db"))
    chunk: ChunkConfig = Field(default_factory=ChunkConfig)
    collections: dict[str, str] = Field(
        default_factory=lambda: {
            "python": "python",
            "markdown": "markdown",
            "config": "config",
        }
    )


class CompanionConfig(BaseModel):
    """Configuration for the companion system.

    Note: CairnWorkspaceService is NOT in this config — it is a required
    argument to start_companion() because it must be shared with the rest
    of the LSP server. Do not add cairn_service here.
    """

    workspace_path: Path = Field(default_factory=Path.cwd)
    indexing: IndexingConfig = Field(default_factory=IndexingConfig)
    auto_index: bool = True
    max_active_agents: int = 20
    agent_idle_timeout_s: float = 300.0
    model_name: str = "Qwen/Qwen3-4B"
    model_base_url: str = "http://localhost:8000/v1"
    model_api_key: str = ""
    max_turns_per_message: int = 10


__all__ = ["CompanionConfig", "IndexingConfig"]
