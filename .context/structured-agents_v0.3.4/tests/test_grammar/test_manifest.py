import yaml
from pathlib import Path

import pytest

from structured_agents.agent import load_manifest
from structured_agents.grammar import DecodingConstraint


def test_manifest_without_grammar(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    agent_dir = bundle_dir / "agents"
    agent_dir.mkdir()
    manifest_path = bundle_dir / "bundle.yaml"
    manifest_data = {
        "name": "no-grammar",
        "initial_context": {"system_prompt": "hi"},
        "agents_dir": "agents",
    }
    manifest_path.write_text(yaml.dump(manifest_data))

    manifest = load_manifest(bundle_dir)
    assert manifest.grammar_config is None


def test_manifest_with_grammar(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    agent_dir = bundle_dir / "agents"
    agent_dir.mkdir()
    manifest_path = bundle_dir / "bundle.yaml"
    manifest_data = {
        "name": "with-grammar",
        "initial_context": {"system_prompt": "hi"},
        "agents_dir": "agents",
        "grammar": {"strategy": "json_schema", "allow_parallel_calls": True},
    }
    manifest_path.write_text(yaml.dump(manifest_data))

    manifest = load_manifest(bundle_dir)
    assert isinstance(manifest.grammar_config, DecodingConstraint)
    assert manifest.grammar_config.strategy == "json_schema"
