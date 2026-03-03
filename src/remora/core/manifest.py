# src/remora/core/manifest.py
"""Bundle manifest loading for Remora agents.

This module provides local manifest loading, replacing the removed
structured_agents.agent.load_manifest function.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from structured_agents import DecodingConstraint


@dataclass
class BundleManifest:
    """Manifest for an agent bundle.

    Attributes:
        name: Bundle/agent name
        system_prompt: System prompt for the agent
        agents_dir: Absolute path to .pym tools directory (resolved from bundle)
        model: Model identifier string
        grammar_config: Optional grammar constraint configuration
        max_turns: Maximum agent loop iterations
        requires_context: Whether agent needs context in prompts
        limits: Optional resource limits for tool execution
    """

    name: str = ""
    system_prompt: str = ""
    agents_dir: Path | None = None
    model: str = "qwen"
    grammar_config: DecodingConstraint | None = None
    max_turns: int = 20
    requires_context: bool = True
    limits: dict[str, Any] | None = None


def load_manifest(bundle_path: str | Path) -> BundleManifest:
    """Load a bundle manifest from path.

    This function replicates the logic from the removed
    structured_agents.agent.load_manifest, including:
    - Path resolution for agents_dir (relative to bundle)
    - Grammar config parsing (dict -> DecodingConstraint)
    - Model config parsing (string or dict format)

    Args:
        bundle_path: Path to bundle directory or bundle.yaml file

    Returns:
        Parsed BundleManifest with resolved paths

    Example:
        >>> manifest = load_manifest("bundles/code-agent")
        >>> manifest.agents_dir
        PosixPath('/path/to/bundles/code-agent/agents')
        >>> manifest.grammar_config
        DecodingConstraint(strategy='structural_tag', ...)
    """
    path = Path(bundle_path)
    if path.is_dir():
        manifest_path = path / "bundle.yaml"
    else:
        manifest_path = path

    bundle_dir = manifest_path.parent

    if not manifest_path.exists():
        return BundleManifest()

    data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}

    # Parse initial_context for system_prompt (original format)
    initial_context = data.get("initial_context", {})
    system_prompt = initial_context.get("system_prompt", "")
    # Also support flat system_prompt key
    if not system_prompt:
        system_prompt = data.get("system_prompt", "")

    # Parse model config (can be string or dict)
    model_config = data.get("model", "qwen")
    if isinstance(model_config, dict):
        model_name = model_config.get("plugin") or model_config.get("id") or model_config.get("name") or "qwen"
    else:
        model_name = str(model_config)

    # Parse grammar config -> DecodingConstraint
    grammar_config = None
    grammar_data = data.get("grammar", {})
    if grammar_data:
        grammar_config = DecodingConstraint(
            strategy=grammar_data.get("strategy", "structural_tag"),
            allow_parallel_calls=grammar_data.get("allow_parallel_calls", False),
            send_tools_to_api=grammar_data.get("send_tools_to_api", False),
        )

    # Resolve agents_dir relative to bundle directory
    agents_dir_raw = data.get("agents_dir")
    agents_dir = bundle_dir / agents_dir_raw if agents_dir_raw else None

    return BundleManifest(
        name=data.get("name", "unnamed"),
        system_prompt=system_prompt,
        agents_dir=agents_dir,
        model=model_name,
        grammar_config=grammar_config,
        max_turns=data.get("max_turns", 20),
        requires_context=data.get("requires_context", True),
        limits=data.get("limits"),
    )


__all__ = ["BundleManifest", "load_manifest"]
