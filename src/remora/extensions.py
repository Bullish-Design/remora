"""AgentExtension base class and config loader.

Extension configs live in `.remora/models/`. They are Python classes
with two static methods: matches() and get_extension_data().
First match wins. File-alphabetical order controls priority.
"""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from typing import Type

logger = logging.getLogger(__name__)


class AgentExtension:
    """Base class for agent extension configs.

    Subclass this in `.remora/models/*.py` files. Override:
    - matches(node_type, name) -> bool
    - get_extension_data() -> dict of AgentNode field overrides
    """

    @staticmethod
    def matches(node_type: str, name: str) -> bool:
        """Return True if this extension applies to the given node."""
        return False

    @staticmethod
    def get_extension_data() -> dict:
        """Return field overrides for the AgentNode."""
        return {}


# Module-level cache: {dir_path: (mtimes_dict, extensions_list)}
_cache: dict[str, tuple[dict[Path, float], list[Type[AgentExtension]]]] = {}


def load_extensions(models_dir: Path) -> list[Type[AgentExtension]]:
    """Load extension configs from a directory with mtime-based caching.

    Returns extensions sorted by filename (alphabetical).
    First match wins, so developers control priority via naming
    (e.g., 00_specific.py before 50_generic.py).
    """
    global _cache

    if not models_dir.exists():
        return []

    cache_key = str(models_dir)

    # Collect current mtimes
    current_mtimes: dict[Path, float] = {}
    for py_file in sorted(models_dir.glob("*.py")):
        try:
            current_mtimes[py_file] = py_file.stat().st_mtime
        except OSError:
            pass

    # Check cache
    if cache_key in _cache:
        cached_mtimes, cached_extensions = _cache[cache_key]
        if current_mtimes == cached_mtimes and cached_mtimes:
            return cached_extensions

    # Reload
    extensions: list[Type[AgentExtension]] = []

    for py_file in sorted(current_mtimes.keys()):
        try:
            spec = importlib.util.spec_from_file_location(py_file.stem, py_file)
            if not spec or not spec.loader:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            for obj in module.__dict__.values():
                if isinstance(obj, type) and issubclass(obj, AgentExtension) and obj is not AgentExtension:
                    extensions.append(obj)
        except Exception as e:
            logger.warning("Failed to load extension from %s: %s", py_file, e)
            continue

    _cache[cache_key] = (current_mtimes, extensions)
    return extensions
