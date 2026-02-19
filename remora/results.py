"""Result schemas and formatting for Remora."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class AgentStatus:
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class AgentResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: Literal["success", "failed", "skipped"]
    workspace_id: str
    changed_files: list[str] = Field(default_factory=list)
    summary: str = ""
    details: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class NodeResult(BaseModel):
    node_id: str
    node_name: str
    file_path: Path
    operations: dict[str, AgentResult] = Field(default_factory=dict)
    errors: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def all_success(self) -> bool:
        return all(result.status == AgentStatus.SUCCESS for result in self.operations.values())


class AnalysisResults(BaseModel):
    """Complete results from analyzing a codebase."""

    nodes: list[NodeResult] = Field(default_factory=list)
    total_nodes: int = 0
    total_operations: int = 0
    successful_operations: int = 0
    failed_operations: int = 0
    skipped_operations: int = 0

    @classmethod
    def from_node_results(cls, results: list[NodeResult]) -> "AnalysisResults":
        """Build AnalysisResults from a list of NodeResult objects."""
        successful = sum(1 for nr in results for ar in nr.operations.values() if ar.status == AgentStatus.SUCCESS)
        failed = sum(1 for nr in results for ar in nr.operations.values() if ar.status == AgentStatus.FAILED)
        skipped = sum(1 for nr in results for ar in nr.operations.values() if ar.status == AgentStatus.SKIPPED)
        total_ops = sum(len(nr.operations) for nr in results)

        return cls(
            nodes=results,
            total_nodes=len(results),
            total_operations=total_ops,
            successful_operations=successful,
            failed_operations=failed,
            skipped_operations=skipped,
        )

    def to_json(self) -> str:
        """Serialize to JSON."""
        return self.model_dump_json(indent=2)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return self.model_dump(mode="json")
