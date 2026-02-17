"""Result schemas and formatting for Remora."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AgentResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: Literal["success", "failed", "skipped"]
    workspace_id: str
    changed_files: list[str] = Field(default_factory=list)
    summary: str = ""
    details: dict = Field(default_factory=dict)
    error: str | None = None


class NodeResult(BaseModel):
    node_id: str
    node_name: str
    file_path: Path
    operations: dict[str, AgentResult] = Field(default_factory=dict)
    errors: list[dict] = Field(default_factory=list)

    @property
    def all_success(self) -> bool:
        return all(result.status == "success" for result in self.operations.values())
