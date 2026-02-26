# Implementation Guide: Step 3 — Flatten Configuration

## Overview

This step creates a two-level configuration system as described in Idea 10 of the design document.

- **Level 1: `remora.yaml`** — Project-level configuration (loaded once at startup)
- **Level 2: `bundle.yaml`** — Per-agent configuration (structured-agents v0.3 format)

## Current State (What You're Replacing)

- `src/remora/config.py` — 342 lines, deeply nested Pydantic models (ServerConfig, RunnerConfig, DiscoveryConfig, CairnConfig, HubConfig)
- `src/remora/constants.py` — 15 lines, hardcoded constants

## Target State

- `src/remora/config.py` — Frozen dataclass with RemoraConfig, loaded once at startup
- Configuration covers: discovery paths, bundle mapping, execution settings, indexer, dashboard, workspace, model
- `constants.py` deleted (absorbed into config defaults)
- `remora.example.yaml` created as reference

---

## Implementation Steps

### Step 3.1: Rewrite `src/remora/config.py`

Replace the entire file with the following implementation:

```python
"""src/remora/config.py

Two-level configuration system:
- remora.yaml: Project-level config (loaded once at startup)
- bundle.yaml: Per-agent config (structured-agents v0.3 format)

Configuration precedence (highest to lowest):
1. Environment variables (REMORA_* prefix)
2. YAML file (remora.yaml)
3. Code defaults
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class DiscoveryConfig:
    """Configuration for code discovery."""
    paths: list[str] = field(default_factory=lambda: ["src/"])
    languages: list[str] = field(default_factory=lambda: ["python", "markdown"])


@dataclass(frozen=True)
class BundleConfig:
    """Configuration for agent bundles."""
    path: str = "agents"
    mapping: dict[str, str] = field(default_factory=lambda: {
        "function": "lint",
        "class": "docstring",
        "file": "test",
    })


@dataclass(frozen=True)
class ExecutionConfig:
    """Configuration for graph execution."""
    max_concurrency: int = 4
    error_policy: str = "skip_downstream"  # stop_graph | skip_downstream | continue
    timeout: int = 300


@dataclass(frozen=True)
class IndexerConfig:
    """Configuration for the indexer daemon."""
    watch_paths: list[str] = field(default_factory=lambda: ["src/"])
    store_path: str = ".remora/index"


@dataclass(frozen=True)
class DashboardConfig:
    """Configuration for the web dashboard."""
    host: str = "0.0.0.0"
    port: int = 8420


@dataclass(frozen=True)
class WorkspaceConfig:
    """Configuration for Cairn workspaces."""
    base_path: str = ".remora/workspaces"
    cleanup_after: str = "1h"  # "1h", "24h", "7d", etc.


@dataclass(frozen=True)
class ModelConfig:
    """Configuration for the LLM model (used by bundles that don't specify their own)."""
    base_url: str = "http://localhost:8000/v1"
    default_model: str = "Qwen/Qwen3-4B"


@dataclass(frozen=True)
class RemoraConfig:
    """Root configuration object. Immutable after load."""
    discovery: DiscoveryConfig = field(default_factory=DiscoveryConfig)
    bundles: BundleConfig = field(default_factory=BundleConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    indexer: IndexerConfig = field(default_factory=IndexerConfig)
    dashboard: DashboardConfig = field(default_factory=DashboardConfig)
    workspace: WorkspaceConfig = field(default_factory=WorkspaceConfig)
    model: ModelConfig = field(default_factory=ModelConfig)


def load_config(config_path: Path | None = None) -> RemoraConfig:
    """Load configuration from YAML file.
    
    Loads remora.yaml from the current directory if no path is specified.
    Environment variables override file config (e.g., REMORA_MODEL_BASE_URL).
    
    Args:
        config_path: Path to remora.yaml. Defaults to ./remora.yaml
        
    Returns:
        Frozen RemoraConfig instance
        
    Raises:
        FileNotFoundError: If config file doesn't exist
        ValueError: If config file is invalid
    """
    if config_path is None:
        config_path = Path.cwd() / "remora.yaml"
    
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    
    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML in config file: {e}") from e
    
    if data is None:
        data = {}
    
    if not isinstance(data, dict):
        raise ValueError("Config file must define a mapping.")
    
    # Apply environment variable overrides
    data = _apply_env_overrides(data)
    
    # Build config with defaults
    return _build_config(data)


def _apply_env_overrides(data: dict[str, Any]) -> dict[str, Any]:
    """Apply environment variable overrides to config.
    
    Environment variables must be prefixed with REMORA_ and use double underscores
    for nesting. Example: REMORA_MODEL__BASE_URL sets model.base_url.
    
    Args:
        data: Base config dictionary
        
    Returns:
        Updated config with environment overrides applied
    """
    import os
    
    for key, value in os.environ.items():
        if not key.startswith("REMORA_"):
            continue
        
        # Convert REMORA_MODEL__BASE_URL -> model.base_url
        parts = key[7:].lower().split("__")
        
        # Navigate to the right nested location
        current = data
        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]
        
        # Set the final key
        final_key = parts[-1]
        current[final_key] = _parse_env_value(value)
    
    return data


def _parse_env_value(value: str) -> Any:
    """Parse environment variable value to appropriate type."""
    # Handle booleans
    if value.lower() in ("true", "yes", "1"):
        return True
    if value.lower() in ("false", "no", "0"):
        return False
    
    # Handle integers
    try:
        return int(value)
    except ValueError:
        pass
    
    # Handle floats
    try:
        return float(value)
    except ValueError:
        pass
    
    # Return as string
    return value


def _build_config(data: dict[str, Any]) -> RemoraConfig:
    """Build RemoraConfig from parsed YAML data."""
    
    # Discovery config
    discovery_data = data.get("discovery", {})
    discovery = DiscoveryConfig(
        paths=discovery_data.get("paths", ["src/"]),
        languages=discovery_data.get("languages", ["python", "markdown"]),
    )
    
    # Bundle config
    bundles_data = data.get("bundles", {})
    bundles = BundleConfig(
        path=bundles_data.get("path", "agents"),
        mapping=bundles_data.get("mapping", {
            "function": "lint",
            "class": "docstring",
            "file": "test",
        }),
    )
    
    # Execution config
    execution_data = data.get("execution", {})
    execution = ExecutionConfig(
        max_concurrency=execution_data.get("max_concurrency", 4),
        error_policy=execution_data.get("error_policy", "skip_downstream"),
        timeout=execution_data.get("timeout", 300),
    )
    
    # Indexer config
    indexer_data = data.get("indexer", {})
    indexer = IndexerConfig(
        watch_paths=indexer_data.get("watch_paths", ["src/"]),
        store_path=indexer_data.get("store_path", ".remora/index"),
    )
    
    # Dashboard config
    dashboard_data = data.get("dashboard", {})
    dashboard = DashboardConfig(
        host=dashboard_data.get("host", "0.0.0.0"),
        port=dashboard_data.get("port", 8420),
    )
    
    # Workspace config
    workspace_data = data.get("workspace", {})
    workspace = WorkspaceConfig(
        base_path=workspace_data.get("base_path", ".remora/workspaces"),
        cleanup_after=workspace_data.get("cleanup_after", "1h"),
    )
    
    # Model config
    model_data = data.get("model", {})
    model = ModelConfig(
        base_url=model_data.get("base_url", "http://localhost:8000/v1"),
        default_model=model_data.get("default_model", "Qwen/Qwen3-4B"),
    )
    
    return RemoraConfig(
        discovery=discovery,
        bundles=bundles,
        execution=execution,
        indexer=indexer,
        dashboard=dashboard,
        workspace=workspace,
        model=model,
    )
```

### Step 3.2: Update `src/remora/__init__.py`

Add the `load_config` function to the public API:

```python
from remora.config import load_config, RemoraConfig
```

### Step 3.3: Handle Constants Migration

The constants in `constants.py` need to be migrated:

| Constant | New Location |
|----------|--------------|
| `TERMINATION_TOOL` | Removed (handled by bundle.yaml) |
| `CONFIG_DIR` | Removed (handled by config paths) |
| `CACHE_DIR` | Removed (handled by config) |
| `HUB_DB_NAME` | Removed (handled by indexer config) |
| `DEFAULT_OPERATIONS` | Removed (handled by bundle mapping) |

After confirming no other files import from `constants.py`, delete the file:

```bash
rm src/remora/constants.py
```

To verify no imports exist:
```bash
grep -r "from remora.constants import" src/
grep -r "from remora import constants" src/
```

### Step 3.4: Create Example Config File

Create `remora.example.yaml` in the project root:

```yaml
# Remora Configuration Example
# Copy this file to remora.yaml and customize for your project

# Where to find source code for discovery
discovery:
  paths:
    - "src/"
  languages:
    - "python"
    - "markdown"

# Where to find agent bundles and how to map node types to bundles
bundles:
  path: "agents"
  mapping:
    function: lint
    class: docstring
    file: test

# Graph execution settings
execution:
  max_concurrency: 4
  error_policy: skip_downstream  # stop_graph | skip_downstream | continue
  timeout: 300

# Indexer daemon settings
indexer:
  watch_paths:
    - "src/"
  store_path: ".remora/index"

# Dashboard web server settings
dashboard:
  host: "0.0.0.0"
  port: 8420

# Cairn workspace settings
workspace:
  base_path: ".remora/workspaces"
  cleanup_after: "1h"  # "1h", "24h", "7d", "never"

# Default model settings (used by bundles that don't specify their own)
model:
  base_url: "http://localhost:8000/v1"
  default_model: "Qwen/Qwen3-4B"
```

### Step 3.5: Write Tests

Create `tests/test_config.py`:

```python
"""Tests for the configuration system."""

import os
import tempfile
from pathlib import Path

import pytest

from remora.config import (
    load_config,
    RemoraConfig,
    DiscoveryConfig,
    BundleConfig,
    ExecutionConfig,
    IndexerConfig,
    DashboardConfig,
    WorkspaceConfig,
    ModelConfig,
)


class TestLoadConfig:
    """Tests for load_config function."""
    
    def test_load_valid_config(self, tmp_path):
        """Test loading a valid configuration file."""
        config_file = tmp_path / "remora.yaml"
        config_file.write_text("""
discovery:
  paths:
    - "src/"
    - "tests/"
  languages:
    - "python"

bundles:
  path: "my_agents"
  mapping:
    function: lint
    class: docstring

execution:
  max_concurrency: 8
  error_policy: stop_graph
  timeout: 600

indexer:
  watch_paths:
    - "lib/"
  store_path: ".index"

dashboard:
  host: "127.0.0.1"
  port: 9000

workspace:
  base_path: ".workspaces"
  cleanup_after: "24h"

model:
  base_url: "http://custom:8000/v1"
  default_model: "custom/model"
""")
        
        config = load_config(config_file)
        
        assert config.discovery.paths == ["src/", "tests/"]
        assert config.discovery.languages == ["python"]
        assert config.bundles.path == "my_agents"
        assert config.bundles.mapping == {"function": "lint", "class": "docstring"}
        assert config.execution.max_concurrency == 8
        assert config.execution.error_policy == "stop_graph"
        assert config.execution.timeout == 600
        assert config.indexer.watch_paths == ["lib/"]
        assert config.indexer.store_path == ".index"
        assert config.dashboard.host == "127.0.0.1"
        assert config.dashboard.port == 9000
        assert config.workspace.base_path == ".workspaces"
        assert config.workspace.cleanup_after == "24h"
        assert config.model.base_url == "http://custom:8000/v1"
        assert config.model.default_model == "custom/model"
    
    def test_missing_config_file(self, tmp_path):
        """Test that missing config file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            load_config(tmp_path / "nonexistent.yaml")
    
    def test_invalid_yaml(self, tmp_path):
        """Test that invalid YAML raises ValueError."""
        config_file = tmp_path / "remora.yaml"
        config_file.write_text("""
discovery:
  paths: this is not a list
""")
        
        with pytest.raises(ValueError, match="Invalid YAML"):
            load_config(config_file)
    
    def test_invalid_yaml_structure(self, tmp_path):
        """Test that non-dict YAML raises ValueError."""
        config_file = tmp_path / "remora.yaml"
        config_file.write_text("- item1\n- item2")
        
        with pytest.raises(ValueError, match="must define a mapping"):
            load_config(config_file)
    
    def test_defaults_used_when_not_specified(self, tmp_path):
        """Test that defaults are used for missing fields."""
        config_file = tmp_path / "remora.yaml"
        config_file.write_text("discovery:\n  paths: []")
        
        config = load_config(config_file)
        
        assert config.discovery.paths == []
        assert config.discovery.languages == ["python", "markdown"]
        assert config.execution.max_concurrency == 4
        assert config.dashboard.port == 8420
    
    def test_environment_variable_overrides(self, tmp_path):
        """Test that environment variables override file config."""
        config_file = tmp_path / "remora.yaml"
        config_file.write_text("""
discovery:
  paths:
    - "src/"
execution:
  max_concurrency: 4
""")
        
        # Set environment variables
        os.environ["REMORA_EXECUTION__MAX_CONCURRENCY"] = "16"
        os.environ["REMORA_MODEL__BASE_URL"] = "http://env:8000/v1"
        
        try:
            config = load_config(config_file)
            
            assert config.execution.max_concurrency == 16
            assert config.model.base_url == "http://env:8000/v1"
            # discovery.paths should still be from file
            assert config.discovery.paths == ["src/"]
        finally:
            del os.environ["REMORA_EXECUTION__MAX_CONCURRENCY"]
            del os.environ["REMORA_MODEL__BASE_URL"]
    
    def test_env_var_parsing(self, tmp_path):
        """Test environment variable value parsing."""
        config_file = tmp_path / "remora.yaml"
        config_file.write_text("execution:\n  max_concurrency: 4")
        
        os.environ["REMORA_EXECUTION__MAX_CONCURRENCY"] = "8"
        os.environ["REMORA_EXECUTION__TIMEOUT"] = "120"
        os.environ["REMORA_DASHBOARD__PORT"] = "9000"
        
        try:
            config = load_config(config_file)
            
            assert config.execution.max_concurrency == 8
            assert config.execution.timeout == 120
            assert config.dashboard.port == 9000
        finally:
            del os.environ["REMORA_EXECUTION__MAX_CONCURRENCY"]
            del os.environ["REMORA_EXECUTION__TIMEOUT"]
            del os.environ["REMORA_DASHBOARD__PORT"]


class TestConfigImmutability:
    """Tests that config objects are immutable."""
    
    def test_config_is_frozen(self, tmp_path):
        """Test that RemoraConfig cannot be modified after creation."""
        config_file = tmp_path / "remora.yaml"
        config_file.write_text("")
        
        config = load_config(config_file)
        
        with pytest.raises(AttributeError):
            config.discovery.paths = []
    
    def test_nested_configs_are_frozen(self, tmp_path):
        """Test that nested config objects cannot be modified."""
        config_file = tmp_path / "remora.yaml"
        config_file.write_text("")
        
        config = load_config(config_file)
        
        with pytest.raises(AttributeError):
            config.discovery.paths.append("new_path")


class TestErrorPolicy:
    """Tests for execution error policy validation."""
    
    def test_valid_error_policies(self, tmp_path):
        """Test that valid error policies are accepted."""
        for policy in ["stop_graph", "skip_downstream", "continue"]:
            config_file = tmp_path / "remora.yaml"
            config_file.write_text(f"execution:\n  error_policy: {policy}")
            
            config = load_config(config_file)
            assert config.execution.error_policy == policy
</file>

### Step 3.6: Verification

Test that the configuration loads correctly:

```bash
# From project root, create a test config
echo 'discovery:
  paths:
    - "src/"
  languages:
    - "python"
bundles:
  path: "agents"
  mapping:
    function: lint
execution:
  max_concurrency: 4
' > /tmp/test_remora.yaml

# Run verification
python -c "
from pathlib import Path
from remora import load_config

config = load_config(Path('/tmp/test_remora.yaml'))
print('Discovery paths:', config.discovery.paths)
print('Languages:', config.discovery.languages)
print('Bundle mapping:', config.bundles.mapping)
print('Max concurrency:', config.execution.max_concurrency)
print('Dashboard port:', config.dashboard.port)
print('Model base_url:', config.model.base_url)
"
```

Run the tests:

```bash
pytest tests/test_config.py -v
```

---

## Files to Modify

| File | Action |
|------|--------|
| `src/remora/config.py` | Rewrite (~150 lines) |
| `src/remora/__init__.py` | Add exports |
| `src/remora/constants.py` | Delete |
| `remora.example.yaml` | Create |
| `tests/test_config.py` | Create |

---

## Common Pitfalls

1. **Don't use Pydantic** — Use frozen dataclasses for simplicity
2. **Config is loaded once** — Not reloaded on file changes
3. **Environment variables override file config** — Use double underscores for nesting
4. **Immutable by default** — All dataclasses use `frozen=True`

---

## What to Preserve

- YAML-based configuration
- All configurable dimensions (paths, concurrency, timeout, ports)
- Override capability via environment variables
- Bundle-specific config still goes in `bundle.yaml` (structured-agents format)
