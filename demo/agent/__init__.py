# demo/agent/__init__.py
"""Demo agent module - re-exports from src/remora/lsp for backward compatibility."""

from remora.lsp.runner import AgentRunner, ExtensionNode, Trigger

__all__ = ["AgentRunner", "ExtensionNode", "Trigger"]
