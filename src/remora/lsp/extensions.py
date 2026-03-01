from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Type

from pydantic import BaseModel, ConfigDict

from remora.lsp.models import ToolSchema


class ExtensionNode(BaseModel):
    model_config = ConfigDict(frozen=False)

    @classmethod
    def matches(cls, node_type: str, name: str) -> bool:
        return False

    @property
    def system_prompt(self) -> str:
        return ""

    def get_workspaces(self) -> str:
        return ""

    def get_tool_schemas(self) -> list[ToolSchema]:
        return []


def load_extensions_from_disk() -> list[Type[ExtensionNode]]:
    extensions: list[Type[ExtensionNode]] = []
    models_dir = Path(".remora/models")

    if not models_dir.exists():
        return extensions

    for py_file in models_dir.glob("*.py"):
        try:
            spec = importlib.util.spec_from_file_location(py_file.stem, py_file)
            if not spec or not spec.loader:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            for obj in module.__dict__.values():
                if isinstance(obj, type) and issubclass(obj, ExtensionNode) and obj is not ExtensionNode:
                    extensions.append(obj)
        except Exception:
            continue

    return extensions
