"""Rules Engine for Hub updates.

The Rules Engine decides what actions to take when a file changes.
It is completely deterministic - no LLM involved.

Design:
- UpdateAction is the unit of work
- RulesEngine maps file changes to actions
- ActionContext provides dependencies for execution
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from remora.hub.store import NodeStateStore


@dataclass
class ActionContext:
    """Context for executing update actions.

    Provides access to store and Grail execution.
    """

    store: "NodeStateStore"
    grail_executor: Any
    project_root: Path

    async def run_grail_script(
        self,
        script_path: str,
        inputs: dict[str, Any],
    ) -> dict[str, Any]:
        """Run a Grail script and return results.

        Args:
            script_path: Path to .pym file (relative to .grail/)
            inputs: Input parameters for the script

        Returns:
            Script output as dict
        """
        return await self.grail_executor.run(
            script_path=script_path,
            inputs=inputs,
            externals={
                "read_file": self._read_file,
            },
        )

    async def _read_file(self, path: str) -> str:
        """External function for Grail scripts to read files."""
        file_path = Path(path)
        if not file_path.is_absolute():
            file_path = self.project_root / file_path
        return file_path.read_text(encoding="utf-8")


@dataclass
class UpdateAction(ABC):
    """Base class for update actions."""

    @abstractmethod
    async def execute(self, context: ActionContext) -> dict[str, Any]:
        """Execute the action.

        Args:
            context: ActionContext with dependencies

        Returns:
            Result dict (action-specific)
        """
        ...


@dataclass
class ExtractSignatures(UpdateAction):
    """Extract signatures from a Python file."""

    file_path: Path

    async def execute(self, context: ActionContext) -> dict[str, Any]:
        """Run the extract_signatures Grail script."""
        return await context.run_grail_script(
            "hub/extract_signatures.pym",
            {"file_path": str(self.file_path)},
        )


@dataclass
class DeleteFileNodes(UpdateAction):
    """Delete all nodes for a deleted file."""

    file_path: Path

    async def execute(self, context: ActionContext) -> dict[str, Any]:
        """Remove all nodes associated with this file."""
        deleted = await context.store.invalidate_file(str(self.file_path))
        return {
            "action": "delete_file_nodes",
            "file_path": str(self.file_path),
            "deleted": deleted,
            "count": len(deleted),
        }


@dataclass
class UpdateNodeState(UpdateAction):
    """Update a single node's state from extraction results."""

    file_path: Path
    node_data: dict[str, Any]
    file_hash: str
    update_source: str

    async def execute(self, context: ActionContext) -> dict[str, Any]:
        """Create/update NodeState from extracted data."""
        from remora.hub.models import NodeState

        node_key = f"node:{self.file_path}:{self.node_data['name']}"

        state = NodeState(
            key=node_key,
            file_path=str(self.file_path),
            node_name=self.node_data["name"],
            node_type=self.node_data["type"],
            source_hash=self.node_data["source_hash"],
            file_hash=self.file_hash,
            signature=self.node_data.get("signature"),
            docstring=self.node_data.get("docstring"),
            decorators=self.node_data.get("decorators", []),
            line_count=self.node_data.get("line_count"),
            has_type_hints=self.node_data.get("has_type_hints", False),
            update_source=self.update_source,
        )

        await context.store.set(state)

        return {
            "action": "update_node_state",
            "key": node_key,
            "node_type": state.node_type,
        }


class RulesEngine:
    """Decides what to recompute when a file changes.

    The rules are deterministic and do not involve any LLM calls.
    """

    def get_actions(
        self,
        change_type: str,
        file_path: Path,
    ) -> list[UpdateAction]:
        """Determine actions to take for a file change.

        Args:
            change_type: Type of file system change
            file_path: Path to the changed file

        Returns:
            List of UpdateAction objects to execute
        """
        actions: list[UpdateAction] = []

        if change_type == "deleted":
            actions.append(DeleteFileNodes(file_path))
            return actions

        actions.append(ExtractSignatures(file_path))

        return actions

    def should_process_file(self, file_path: Path, ignore_patterns: list[str]) -> bool:
        """Check if a file should be processed.

        Args:
            file_path: Path to check
            ignore_patterns: List of path patterns to ignore

        Returns:
            True if file should be processed
        """
        if file_path.suffix != ".py":
            return False

        path_parts = file_path.parts
        for pattern in ignore_patterns:
            if pattern in path_parts:
                return False

        if file_path.name.startswith("."):
            return False

        return True
