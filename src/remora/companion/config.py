"""Configuration for the companion node-agent system."""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field


class IndexingConfig(BaseModel):
    """Vector search configuration.

    Uses plain dictionaries to avoid importing embeddy during core LSP startup.
    Embeddy config models are constructed lazily by IndexingService.
    """

    embedder: dict[str, object] = Field(
        default_factory=lambda: {"mode": "remote", "remote_url": "http://localhost:8586"}
    )
    store: dict[str, object] = Field(default_factory=lambda: {"db_path": ".remora/companion/vectors.db"})
    chunk: dict[str, object] = Field(default_factory=dict)
    collections: dict[str, str] = Field(
        default_factory=lambda: {
            "python": "python",
            "markdown": "markdown",
            "config": "config",
        }
    )

    def resolve_store_db_path(self, workspace_path: Path) -> Path:
        raw_path = str(self.store.get("db_path", ".remora/companion/vectors.db"))
        db_path = Path(raw_path).expanduser()
        if not db_path.is_absolute():
            db_path = workspace_path / db_path
        return db_path


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
