"""Rules Engine for indexer updates."""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from remora.indexer.store import NodeStateStore

SCRIPT_ROOT = Path(__file__).parent / "scripts"


@dataclass
class ActionContext:
    """Context for executing update actions."""

    store: "NodeStateStore"
    grail_executor: Any = None
    project_root: Path = field(default_factory=Path)
    script_root: Path = field(default_factory=lambda: SCRIPT_ROOT)

    async def run_grail_script(
        self,
        script_path: str,
        inputs: dict[str, Any],
    ) -> dict[str, Any]:
        """Run a Grail script and return results."""
        script_file = self.script_root / script_path
        externals = {
            "read_file": self._read_file,
            "extract_signatures": self._extract_signatures,
        }

        if self.grail_executor is not None:
            return await self.grail_executor.run(
                script_path=str(script_file),
                inputs=inputs,
                externals=externals,
            )

        import grail

        grail_dir = self.project_root / ".grail" / "indexer"
        script = grail.load(str(script_file), grail_dir=str(grail_dir))
        result = await script.run(
            inputs=inputs,
            externals=externals,
        )
        return result

    async def _read_file(self, path: str) -> str:
        """External function for Grail scripts to read files."""
        file_path = Path(path)
        if not file_path.is_absolute():
            file_path = self.project_root / file_path
        return file_path.read_text(encoding="utf-8")

    async def _extract_signatures(self, file_path: str) -> dict[str, Any]:
        """External function for Grail scripts to parse signatures."""
        from remora.indexer.scanner import Scanner

        path = Path(file_path)
        if not path.is_absolute():
            path = self.project_root / path

        if not path.exists():
            return {"file_hash": "", "nodes": []}

        content = path.read_text(encoding="utf-8")
        file_hash = hashlib.sha256(content.encode()).hexdigest()

        scanner = Scanner()
        nodes = await scanner.scan_file(path)
        for node in nodes:
            node.setdefault("file_hash", file_hash)
        return {"file_hash": file_hash, "nodes": nodes}


@dataclass
class UpdateAction(ABC):
    """Base class for update actions."""

    @abstractmethod
    async def execute(self, context: ActionContext) -> dict[str, Any]:
        """Execute the action."""
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


class RulesEngine:
    """Decides what to recompute when a file changes."""

    def get_actions(
        self,
        change_type: str,
        file_path: Path,
    ) -> list[UpdateAction]:
        """Determine actions to take for a file change."""
        actions: list[UpdateAction] = []

        if change_type == "deleted":
            actions.append(DeleteFileNodes(file_path))
            return actions

        actions.append(ExtractSignatures(file_path))

        return actions

    def should_process_file(self, file_path: Path, ignore_patterns: list[str]) -> bool:
        """Check if a file should be processed."""
        if file_path.suffix != ".py":
            return False

        path_parts = file_path.parts
        for pattern in ignore_patterns:
            if pattern in path_parts:
                return False

        if file_path.name.startswith("."):
            return False

        return True
