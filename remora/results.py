"""Result schemas and formatting for Remora."""

from __future__ import annotations

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
