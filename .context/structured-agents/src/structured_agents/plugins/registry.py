from __future__ import annotations

from typing import Type

from structured_agents.plugins.function_gemma import FunctionGemmaPlugin
from structured_agents.plugins.protocol import ModelPlugin
from structured_agents.plugins.qwen import QwenPlugin


class PluginRegistry:
    """Registry for model plugins."""

    def __init__(self) -> None:
        self._plugins: dict[str, Type[ModelPlugin]] = {
            "function_gemma": FunctionGemmaPlugin,
            "qwen": QwenPlugin,
        }

    def register(self, name: str, plugin_cls: Type[ModelPlugin]) -> None:
        """Register a plugin class."""
        self._plugins[name] = plugin_cls

    def get(self, name: str) -> ModelPlugin:
        """Get a plugin instance by name."""
        name_lower = name.lower()
        if name_lower not in self._plugins:
            available = ", ".join(self._plugins.keys())
            raise ValueError(f"Unknown plugin: {name}. Available: {available}")
        return self._plugins[name_lower]()

    def list_plugins(self) -> list[str]:
        """List available plugin names."""
        return list(self._plugins.keys())


_default_registry = PluginRegistry()


def register_plugin(name: str, plugin_cls: Type[ModelPlugin]) -> None:
    """Register a plugin in the default registry."""
    _default_registry.register(name, plugin_cls)


def get_plugin(name: str) -> ModelPlugin:
    """Get a plugin from the default registry."""
    return _default_registry.get(name)
