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


_EXTENSIONS_CACHE: tuple[dict[Path, float], list[Type[ExtensionNode]]] = ({}, [])


def load_extensions_from_disk() -> list[Type[ExtensionNode]]:
    global _EXTENSIONS_CACHE
    models_dir = Path(".remora/models")

    if not models_dir.exists():
        return []

    current_mtimes = {}
    for py_file in models_dir.glob("*.py"):
        try:
            current_mtimes[py_file] = py_file.stat().st_mtime
        except OSError:
            pass

    cached_mtimes, cached_extensions = _EXTENSIONS_CACHE
    if current_mtimes == cached_mtimes and cached_mtimes:
        return cached_extensions

    extensions: list[Type[ExtensionNode]] = []

    for py_file in current_mtimes.keys():
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

    _EXTENSIONS_CACHE = (current_mtimes, extensions)
    return extensions
