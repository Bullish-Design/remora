"""Model plugins for structured-agents."""

from structured_agents.plugins.composed import ComposedModelPlugin
from structured_agents.plugins.function_gemma import FunctionGemmaPlugin
from structured_agents.plugins.protocol import ModelPlugin
from structured_agents.plugins.qwen import QwenPlugin
from structured_agents.plugins.registry import (
    PluginRegistry,
    get_plugin,
    register_plugin,
)

__all__ = [
    "ComposedModelPlugin",
    "FunctionGemmaPlugin",
    "ModelPlugin",
    "PluginRegistry",
    "QwenPlugin",
    "get_plugin",
    "register_plugin",
]
