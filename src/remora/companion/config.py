from __future__ import annotations

from pathlib import Path
from uuid import uuid4
from pydantic import BaseModel, Field

from embeddy.config import EmbedderConfig, StoreConfig, ChunkConfig

class IndexingConfig(BaseModel):
    embedder: EmbedderConfig = Field(
        default_factory=lambda: EmbedderConfig(mode="remote")
    )
    store: StoreConfig = Field(
        default_factory=lambda: StoreConfig(db_path=".companion/vectors.db")
    )
    chunk: ChunkConfig = Field(default_factory=ChunkConfig)
    collections: dict[str, str] = Field(default_factory=lambda: {
        "python": "python",
        "markdown": "markdown",
        "config": "config",
    })

class CompanionConfig(BaseModel):
    workspace_path: Path = Field(default_factory=Path.cwd)
    indexing: IndexingConfig = Field(default_factory=IndexingConfig)
    session_id: str = Field(default_factory=lambda: f"companion-{uuid4()}")
    sidebar_output_path: Path | None = None
    auto_index: bool = True
