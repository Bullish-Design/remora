"""Tests for scaffold-node prompt enrichment in SwarmExecutor._build_prompt().

When a node has status='scaffold', _build_prompt() should include additional
context sections: parent source code, sibling names/types, and the scaffold
intent (from ScaffoldRequestEvent).

Non-scaffold nodes should be unaffected.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from remora.core.agent_node import AgentNode
from remora.core.config import Config
from remora.core.swarm_executor import SwarmExecutor, _agent_node_to_cst_node


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(tmp_path: Path, **overrides: Any) -> Config:
    defaults = {
        "project_path": str(tmp_path),
        "bundle_root": str(tmp_path / "agents"),
        "bundle_mapping": {"function": "code", "class": "code", "file": "file"},
        "model_base_url": "http://localhost:8000/v1",
        "model_default": "test/model",
        "model_api_key": "test-key",
        "swarm_root": str(tmp_path / ".remora"),
        "swarm_id": "test-swarm",
        "max_concurrency": 4,
        "max_turns": 3,
        "truncation_limit": 512,
        "timeout_s": 10.0,
        "chat_history_limit": 5,
    }
    defaults.update(overrides)
    return Config(**defaults)


def _make_node(**overrides: Any) -> AgentNode:
    defaults = {
        "node_id": "agent_func_1",
        "node_type": "function",
        "name": "calculate_total",
        "full_name": "billing.calculate_total",
        "file_path": "src/billing.py",
        "start_line": 10,
        "end_line": 25,
        "start_byte": 0,
        "end_byte": 0,
        "source_code": "def calculate_total(items): return sum(items)",
        "source_hash": "abc123",
        "parent_id": None,
        "status": "idle",
    }
    defaults.update(overrides)
    return AgentNode(**defaults)


@pytest.fixture
def executor(tmp_path):
    config = _make_config(tmp_path)
    with patch("remora.core.swarm_executor.build_client") as mock_build_client:
        mock_build_client.return_value = MagicMock()
        return SwarmExecutor(
            config=config,
            event_bus=None,
            event_store=MagicMock(),
            subscriptions=MagicMock(),
            swarm_id="test",
            project_root=tmp_path,
        )


# =========================================================================
# Scaffold Prompt Enrichment
# =========================================================================


class TestScaffoldPromptEnrichment:
    """When a scaffold node gets its prompt built, it should include
    parent source code, sibling info, and the scaffold intent."""

    def test_scaffold_prompt_includes_parent_source(self, executor):
        """Scaffold node prompt should include parent source code section."""
        node = _make_node(
            status="scaffold",
            source_code="class Calculator: pass",
            parent_id="parent_file_1",
        )
        cst_node = _agent_node_to_cst_node(node)

        scaffold_context = {
            "parent_source": "import math\n\nclass MathUtils:\n    pass\n",
            "siblings": [],
            "intent": "",
        }

        prompt = executor._build_prompt(node, cst_node, {}, scaffold_context=scaffold_context)

        assert "## Scaffold Context" in prompt
        assert "### Parent Source" in prompt
        assert "import math" in prompt
        assert "class MathUtils" in prompt

    def test_scaffold_prompt_includes_siblings(self, executor):
        """Scaffold node prompt should list sibling names and types."""
        node = _make_node(
            status="scaffold",
            source_code="def process(): pass",
            parent_id="parent_file_1",
        )
        cst_node = _agent_node_to_cst_node(node)

        scaffold_context = {
            "parent_source": "# parent file",
            "siblings": [
                {"name": "validate_input", "node_type": "function"},
                {"name": "OutputFormatter", "node_type": "class"},
            ],
            "intent": "",
        }

        prompt = executor._build_prompt(node, cst_node, {}, scaffold_context=scaffold_context)

        assert "### Siblings" in prompt
        assert "validate_input" in prompt
        assert "function" in prompt
        assert "OutputFormatter" in prompt
        assert "class" in prompt

    def test_scaffold_prompt_includes_intent(self, executor):
        """Scaffold node prompt should include the intent from ScaffoldRequestEvent."""
        node = _make_node(
            status="scaffold",
            source_code="class HttpClient: pass",
            parent_id="parent_file_1",
        )
        cst_node = _agent_node_to_cst_node(node)

        scaffold_context = {
            "parent_source": "",
            "siblings": [],
            "intent": "HTTP client with retry logic and connection pooling",
        }

        prompt = executor._build_prompt(node, cst_node, {}, scaffold_context=scaffold_context)

        assert "### Intent" in prompt
        assert "HTTP client with retry logic and connection pooling" in prompt

    def test_scaffold_prompt_includes_all_sections(self, executor):
        """Scaffold node prompt should include all three scaffold context subsections."""
        node = _make_node(
            status="scaffold",
            source_code="def fetch_data(): ...",
            parent_id="parent_mod_1",
        )
        cst_node = _agent_node_to_cst_node(node)

        scaffold_context = {
            "parent_source": "class DataService:\n    def __init__(self): pass",
            "siblings": [
                {"name": "save_data", "node_type": "function"},
            ],
            "intent": "Fetch data from the remote API",
        }

        prompt = executor._build_prompt(node, cst_node, {}, scaffold_context=scaffold_context)

        assert "## Scaffold Context" in prompt
        assert "### Parent Source" in prompt
        assert "DataService" in prompt
        assert "### Siblings" in prompt
        assert "save_data" in prompt
        assert "### Intent" in prompt
        assert "Fetch data from the remote API" in prompt

    def test_non_scaffold_node_no_scaffold_section(self, executor):
        """Non-scaffold (idle) nodes should NOT get a scaffold context section."""
        node = _make_node(status="idle")
        cst_node = _agent_node_to_cst_node(node)

        prompt = executor._build_prompt(node, cst_node, {})

        assert "## Scaffold Context" not in prompt
        assert "### Parent Source" not in prompt
        assert "### Siblings" not in prompt
        assert "### Intent" not in prompt

    def test_scaffold_without_context_no_scaffold_section(self, executor):
        """Scaffold node without scaffold_context kwarg should not crash or add section."""
        node = _make_node(status="scaffold", source_code="def foo(): pass")
        cst_node = _agent_node_to_cst_node(node)

        # No scaffold_context passed — should still work, just no extra section
        prompt = executor._build_prompt(node, cst_node, {})

        assert "## Scaffold Context" not in prompt

    def test_scaffold_empty_parent_source_omits_parent_section(self, executor):
        """When parent_source is empty string, the parent section should be omitted."""
        node = _make_node(
            status="scaffold",
            source_code="class Foo: pass",
            parent_id="parent_1",
        )
        cst_node = _agent_node_to_cst_node(node)

        scaffold_context = {
            "parent_source": "",
            "siblings": [{"name": "bar", "node_type": "function"}],
            "intent": "some intent",
        }

        prompt = executor._build_prompt(node, cst_node, {}, scaffold_context=scaffold_context)

        assert "## Scaffold Context" in prompt
        assert "### Parent Source" not in prompt
        assert "### Siblings" in prompt
        assert "### Intent" in prompt

    def test_scaffold_empty_siblings_omits_siblings_section(self, executor):
        """When siblings list is empty, the siblings section should be omitted."""
        node = _make_node(
            status="scaffold",
            source_code="class Foo: pass",
            parent_id="parent_1",
        )
        cst_node = _agent_node_to_cst_node(node)

        scaffold_context = {
            "parent_source": "class Parent: pass",
            "siblings": [],
            "intent": "some intent",
        }

        prompt = executor._build_prompt(node, cst_node, {}, scaffold_context=scaffold_context)

        assert "## Scaffold Context" in prompt
        assert "### Parent Source" in prompt
        assert "### Siblings" not in prompt
        assert "### Intent" in prompt

    def test_scaffold_empty_intent_omits_intent_section(self, executor):
        """When intent is empty string, the intent section should be omitted."""
        node = _make_node(
            status="scaffold",
            source_code="class Foo: pass",
            parent_id="parent_1",
        )
        cst_node = _agent_node_to_cst_node(node)

        scaffold_context = {
            "parent_source": "class Parent: pass",
            "siblings": [{"name": "bar", "node_type": "function"}],
            "intent": "",
        }

        prompt = executor._build_prompt(node, cst_node, {}, scaffold_context=scaffold_context)

        assert "## Scaffold Context" in prompt
        assert "### Parent Source" in prompt
        assert "### Siblings" in prompt
        assert "### Intent" not in prompt

    def test_scaffold_all_empty_no_scaffold_section(self, executor):
        """When all scaffold_context fields are empty, no scaffold section at all."""
        node = _make_node(
            status="scaffold",
            source_code="class Foo: pass",
            parent_id="parent_1",
        )
        cst_node = _agent_node_to_cst_node(node)

        scaffold_context = {
            "parent_source": "",
            "siblings": [],
            "intent": "",
        }

        prompt = executor._build_prompt(node, cst_node, {}, scaffold_context=scaffold_context)

        assert "## Scaffold Context" not in prompt

    def test_existing_prompt_sections_still_present(self, executor):
        """Scaffold enrichment should not remove existing prompt sections."""
        node = _make_node(
            status="scaffold",
            source_code="class Foo: pass",
            parent_id="parent_1",
        )
        cst_node = _agent_node_to_cst_node(node)

        scaffold_context = {
            "parent_source": "# parent code",
            "siblings": [],
            "intent": "test intent",
        }

        prompt = executor._build_prompt(node, cst_node, {}, scaffold_context=scaffold_context)

        # Standard sections should still be there
        assert "# Target:" in prompt
        assert "File:" in prompt
