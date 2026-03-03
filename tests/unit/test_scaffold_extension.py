"""Tests for the scaffold_initializer extension config.

The scaffold_initializer extension matches nodes with stub/empty source_code
and provides a system prompt instructing the agent to self-initialize using
context from its parent and siblings.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from remora.extensions import AgentExtension, extension_matches


# ---------------------------------------------------------------------------
# Helpers to load extensions from the demo models directory
# ---------------------------------------------------------------------------

_DEMO_MODELS_DIR = Path(__file__).resolve().parents[2] / "remora_demo" / "project" / ".remora" / "models"


def _load_extension_class(module_filename: str, class_name: str) -> type:
    """Import an extension class directly from the demo models directory."""
    import importlib.util

    module_path = _DEMO_MODELS_DIR / module_filename
    spec = importlib.util.spec_from_file_location(module_path.stem, module_path)
    assert spec and spec.loader, f"Could not load {module_path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, class_name)


@pytest.fixture()
def ScaffoldInitializerExtension():
    return _load_extension_class("00_scaffold_initializer.py", "ScaffoldInitializerExtension")


# =========================================================================
# matches()
# =========================================================================


class TestScaffoldInitializerMatches:
    """Verify that the extension matches stub nodes and rejects real code."""

    @pytest.fixture(autouse=True)
    def load_ext(self, ScaffoldInitializerExtension):
        self.ext = ScaffoldInitializerExtension

    def test_matches_empty_source(self):
        assert (
            extension_matches(
                self.ext,
                "function",
                "foo",
                source_code="",
            )
            is True
        )

    def test_matches_class_pass(self):
        assert (
            extension_matches(
                self.ext,
                "class",
                "Foo",
                file_path="src/foo.py",
                source_code="class Foo: pass",
            )
            is True
        )

    def test_matches_def_pass(self):
        assert (
            extension_matches(
                self.ext,
                "function",
                "bar",
                file_path="src/bar.py",
                source_code="def bar(): pass",
            )
            is True
        )

    def test_matches_def_ellipsis(self):
        assert (
            extension_matches(
                self.ext,
                "function",
                "baz",
                file_path="src/baz.py",
                source_code="def baz(): ...",
            )
            is True
        )

    def test_does_not_match_real_function(self):
        assert (
            extension_matches(
                self.ext,
                "function",
                "calc",
                file_path="src/calc.py",
                source_code="def calc():\n    return 42",
            )
            is False
        )

    def test_does_not_match_real_class(self):
        assert (
            extension_matches(
                self.ext,
                "class",
                "Foo",
                file_path="src/foo.py",
                source_code="class Foo:\n    def __init__(self):\n        self.x = 1",
            )
            is False
        )

    def test_does_not_match_non_python_with_content(self):
        """Non-.py files with comment-like content should NOT match."""
        assert (
            extension_matches(
                self.ext,
                "file",
                "MONITOR",
                file_path="MONITOR.md",
                source_code="# Activity Log\n",
            )
            is False
        )

    def test_matches_whitespace_only(self):
        assert (
            extension_matches(
                self.ext,
                "file",
                "empty.py",
                source_code="   \n\n  ",
            )
            is True
        )

    def test_matches_any_node_type(self):
        """Scaffold extension should match any node_type, not just function/class."""
        assert (
            extension_matches(
                self.ext,
                "file",
                "module.py",
                source_code="",
            )
            is True
        )


# =========================================================================
# get_extension_data()
# =========================================================================


class TestScaffoldInitializerExtensionData:
    """Verify the extension provides the correct data."""

    @pytest.fixture(autouse=True)
    def load_ext(self, ScaffoldInitializerExtension):
        self.ext = ScaffoldInitializerExtension

    def test_has_extension_name(self):
        data = self.ext.get_extension_data()
        assert "extension_name" in data
        assert data["extension_name"] == "ScaffoldInitializer"

    def test_has_system_prompt(self):
        data = self.ext.get_extension_data()
        assert "custom_system_prompt" in data
        prompt = data["custom_system_prompt"]
        # The prompt should mention key scaffold concepts
        assert "scaffold" in prompt.lower() or "initialize" in prompt.lower()
        assert "rewrite_self" in prompt

    def test_has_scaffold_subscription(self):
        data = self.ext.get_extension_data()
        assert "extra_subscriptions" in data
        subs = data["extra_subscriptions"]
        assert len(subs) >= 1
        # Should subscribe to ScaffoldRequestEvent
        event_types = []
        for sub in subs:
            event_types.extend(sub.get("event_types", []))
        assert "ScaffoldRequestEvent" in event_types

    def test_is_agent_extension_subclass(self):
        assert issubclass(self.ext, AgentExtension)
