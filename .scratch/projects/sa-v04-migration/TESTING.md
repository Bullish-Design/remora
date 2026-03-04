# Testing Plan for v0.4 Migration

## Overview

After completing the migration, run these tests to verify everything works.

## Unit Tests

### 1. Test manifest.py

Create `tests/unit/test_manifest.py`:

```python
"""Tests for remora.core.manifest module."""

import pytest
from pathlib import Path
import tempfile

from remora.core.manifest import BundleManifest, load_manifest
from structured_agents import DecodingConstraint


class TestLoadManifest:
    """Tests for load_manifest function."""

    def test_load_missing_file_returns_default(self, tmp_path: Path):
        """Missing manifest returns default BundleManifest."""
        manifest = load_manifest(tmp_path / "nonexistent")
        assert manifest.name == ""
        assert manifest.agents_dir is None

    def test_load_from_directory(self, tmp_path: Path):
        """Load manifest from bundle directory."""
        bundle_yaml = tmp_path / "bundle.yaml"
        bundle_yaml.write_text("""
name: test-agent
system_prompt: "Hello"
agents_dir: tools
max_turns: 5
""")
        manifest = load_manifest(tmp_path)
        assert manifest.name == "test-agent"
        assert manifest.system_prompt == "Hello"
        assert manifest.agents_dir == tmp_path / "tools"
        assert manifest.max_turns == 5

    def test_load_from_file(self, tmp_path: Path):
        """Load manifest from direct file path."""
        bundle_yaml = tmp_path / "bundle.yaml"
        bundle_yaml.write_text("name: direct-load")
        manifest = load_manifest(bundle_yaml)
        assert manifest.name == "direct-load"

    def test_agents_dir_resolved_relative_to_bundle(self, tmp_path: Path):
        """agents_dir should be absolute, resolved from bundle location."""
        bundle_yaml = tmp_path / "bundle.yaml"
        bundle_yaml.write_text("agents_dir: my_agents")
        manifest = load_manifest(tmp_path)
        assert manifest.agents_dir == tmp_path / "my_agents"
        assert manifest.agents_dir.is_absolute()

    def test_grammar_config_parsed(self, tmp_path: Path):
        """Grammar config dict should become DecodingConstraint."""
        bundle_yaml = tmp_path / "bundle.yaml"
        bundle_yaml.write_text("""
grammar:
  strategy: structural_tag
  send_tools_to_api: true
  allow_parallel_calls: false
""")
        manifest = load_manifest(tmp_path)
        assert manifest.grammar_config is not None
        assert isinstance(manifest.grammar_config, DecodingConstraint)
        assert manifest.grammar_config.strategy == "structural_tag"
        assert manifest.grammar_config.send_tools_to_api is True

    def test_model_string_format(self, tmp_path: Path):
        """Model as plain string."""
        bundle_yaml = tmp_path / "bundle.yaml"
        bundle_yaml.write_text("model: Qwen/Qwen3-4B")
        manifest = load_manifest(tmp_path)
        assert manifest.model == "Qwen/Qwen3-4B"

    def test_model_dict_format(self, tmp_path: Path):
        """Model as dict with plugin key."""
        bundle_yaml = tmp_path / "bundle.yaml"
        bundle_yaml.write_text("""
model:
  plugin: qwen
  id: custom-id
""")
        manifest = load_manifest(tmp_path)
        assert manifest.model == "qwen"

    def test_system_prompt_in_initial_context(self, tmp_path: Path):
        """System prompt under initial_context (legacy format)."""
        bundle_yaml = tmp_path / "bundle.yaml"
        bundle_yaml.write_text("""
initial_context:
  system_prompt: "Legacy format prompt"
""")
        manifest = load_manifest(tmp_path)
        assert manifest.system_prompt == "Legacy format prompt"

    def test_system_prompt_flat(self, tmp_path: Path):
        """System prompt at top level (new format)."""
        bundle_yaml = tmp_path / "bundle.yaml"
        bundle_yaml.write_text('system_prompt: "Flat format prompt"')
        manifest = load_manifest(tmp_path)
        assert manifest.system_prompt == "Flat format prompt"


class TestBundleManifest:
    """Tests for BundleManifest dataclass."""

    def test_defaults(self):
        """Default values are sensible."""
        m = BundleManifest()
        assert m.name == ""
        assert m.model == "qwen"
        assert m.max_turns == 20
        assert m.requires_context is True
        assert m.grammar_config is None
        assert m.agents_dir is None
```

### 2. Test kernel_factory.py

```python
"""Tests for remora.core.kernel_factory after v0.4 migration."""

import pytest
from unittest.mock import patch, MagicMock

from remora.core.kernel_factory import create_kernel
from structured_agents import AgentKernel, DecodingConstraint


class TestCreateKernel:
    """Tests for create_kernel function."""

    def test_creates_kernel_basic(self):
        """Basic kernel creation works."""
        kernel = create_kernel(
            model_name="test-model",
            base_url="http://localhost:8000/v1",
            api_key="EMPTY",
        )
        assert isinstance(kernel, AgentKernel)
        assert kernel.client is not None
        assert kernel.response_parser is not None
        assert kernel.constraint_pipeline is None

    def test_creates_kernel_with_tools(self):
        """Kernel with tools."""
        mock_tool = MagicMock()
        mock_tool.schema.name = "test_tool"
        
        kernel = create_kernel(
            model_name="test-model",
            base_url="http://localhost:8000/v1",
            api_key="EMPTY",
            tools=[mock_tool],
        )
        assert len(kernel.tools) == 1

    def test_creates_kernel_with_grammar(self):
        """Kernel with grammar constraints."""
        grammar_config = DecodingConstraint(
            strategy="structural_tag",
            send_tools_to_api=False,
        )
        kernel = create_kernel(
            model_name="hosted_vllm/Qwen/Qwen3-4B",
            base_url="http://localhost:8000/v1",
            api_key="EMPTY",
            grammar_config=grammar_config,
        )
        assert kernel.constraint_pipeline is not None

    def test_reuses_provided_client(self):
        """Provided client is reused, not replaced."""
        mock_client = MagicMock()
        mock_client.model = "test-model"
        
        kernel = create_kernel(
            model_name="test-model",
            base_url="http://localhost:8000/v1",
            api_key="EMPTY",
            client=mock_client,
        )
        assert kernel.client is mock_client
```

## Integration Tests

### 3. Test SwarmExecutor Still Works

```python
"""Integration test for SwarmExecutor with v0.4 structured-agents."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from remora.core.swarm_executor import SwarmExecutor
from remora.core.agent_node import AgentNode


@pytest.mark.integration
class TestSwarmExecutorV04:
    """Verify SwarmExecutor works with v0.4 API."""

    @pytest.fixture
    def mock_config(self, tmp_path: Path):
        """Create mock config."""
        config = MagicMock()
        config.model_base_url = "http://localhost:8000/v1"
        config.model_api_key = "EMPTY"
        config.model_default = "test-model"
        config.timeout_s = 30.0
        config.bundle_root = str(tmp_path / "bundles")
        config.bundle_mapping = {"function": "code-agent"}
        config.swarm_root = tmp_path / "swarm"
        config.chat_history_limit = 10
        config.truncation_limit = 1000
        config.max_turns = 5
        return config

    @pytest.fixture
    def sample_bundle(self, mock_config, tmp_path: Path):
        """Create sample bundle."""
        bundle_dir = Path(mock_config.bundle_root) / "code-agent"
        bundle_dir.mkdir(parents=True)
        (bundle_dir / "bundle.yaml").write_text("""
name: code-agent
system_prompt: "You are a code assistant"
agents_dir: agents
max_turns: 3
""")
        (bundle_dir / "agents").mkdir()
        return bundle_dir

    async def test_executor_loads_manifest(self, mock_config, sample_bundle):
        """SwarmExecutor can load manifest with new local implementation."""
        # This test verifies the import chain works
        from remora.core.manifest import load_manifest
        
        manifest = load_manifest(sample_bundle)
        assert manifest.name == "code-agent"
        assert manifest.agents_dir == sample_bundle / "agents"
```

## Running Tests

```bash
# Run all unit tests
uv run pytest tests/unit/test_manifest.py -v

# Run kernel factory tests
uv run pytest tests/unit/test_kernel_factory.py -v

# Run integration tests (requires mock or real vLLM)
uv run pytest tests/integration/ -v -m integration

# Run full suite
uv run pytest tests/ -v
```

## Manual Verification

After migration, manually verify:

1. **Import chain works:**
   ```python
   python -c "from remora.core.kernel_factory import create_kernel; print('OK')"
   python -c "from remora.core.swarm_executor import SwarmExecutor; print('OK')"
   ```

2. **Kernel creation:**
   ```python
   from remora.core.kernel_factory import create_kernel
   k = create_kernel(model_name="test", base_url="http://localhost:8000/v1", api_key="x")
   print(k.response_parser)  # Should print parser instance
   ```

3. **Manifest loading:**
   ```python
   from remora.core.manifest import load_manifest
   m = load_manifest("path/to/bundle")
   print(m.agents_dir)  # Should be absolute Path
   ```
