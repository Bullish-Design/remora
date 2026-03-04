"""Tests for AgentExtension base class and loader."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from remora.extensions import AgentExtension, load_extensions
from remora.extensions import extension_matches


class TestAgentExtensionBase:
    def test_base_matches_returns_false(self):
        assert AgentExtension.matches("function", "foo") is False

    def test_base_matches_accepts_keyword_args(self):
        """matches() should accept file_path and source_code kwargs."""
        result = AgentExtension.matches("function", "foo", file_path="src/main.py", source_code="def foo(): pass")
        assert result is False

    def test_base_get_extension_data_returns_empty(self):
        data = AgentExtension.get_extension_data()
        assert data == {}


class TestExtensionMatchesWidenedAPI:
    """Extensions can match on file_path and source_code."""

    def test_extension_matches_on_decorator(self, tmp_path: Path):
        """An extension can inspect source_code to match on decorators."""
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        ext_file = models_dir / "route_agent.py"
        ext_file.write_text(
            textwrap.dedent("""\
            from remora.extensions import AgentExtension

            class RouteExtension(AgentExtension):
                @staticmethod
                def matches(node_type: str, name: str, *, file_path: str = "", source_code: str = "") -> bool:
                    return "@app.route" in source_code

                @staticmethod
                def get_extension_data() -> dict:
                    return {"extension_name": "RouteAgent"}
        """)
        )

        # Clear module-level cache to avoid stale state
        from remora.extensions import _cache

        _cache.clear()

        exts = load_extensions(models_dir)
        assert len(exts) == 1

        # Should match when source contains the decorator
        assert exts[0].matches("function", "index", source_code='@app.route("/")\ndef index(): ...') is True
        # Should not match when source doesn't contain the decorator
        assert exts[0].matches("function", "helper", source_code="def helper(): pass") is False

    def test_extension_matches_on_file_path(self, tmp_path: Path):
        """An extension can inspect file_path to scope to specific directories."""
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        ext_file = models_dir / "test_runner.py"
        ext_file.write_text(
            textwrap.dedent("""\
            from remora.extensions import AgentExtension

            class TestRunnerExtension(AgentExtension):
                @staticmethod
                def matches(node_type: str, name: str, *, file_path: str = "", source_code: str = "") -> bool:
                    return file_path.startswith("tests/")

                @staticmethod
                def get_extension_data() -> dict:
                    return {"extension_name": "TestRunner"}
        """)
        )

        from remora.extensions import _cache

        _cache.clear()

        exts = load_extensions(models_dir)
        assert len(exts) == 1
        assert exts[0].matches("function", "test_foo", file_path="tests/test_main.py") is True
        assert exts[0].matches("function", "test_foo", file_path="src/main.py") is False


class TestLoadExtensions:
    def test_load_from_empty_dir(self, tmp_path: Path):
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        exts = load_extensions(models_dir)
        assert exts == []

    def test_load_from_nonexistent_dir(self, tmp_path: Path):
        exts = load_extensions(tmp_path / "nonexistent")
        assert exts == []

    def test_load_valid_extension(self, tmp_path: Path):
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        ext_file = models_dir / "test_agent.py"
        ext_file.write_text(
            textwrap.dedent("""\
            from remora.extensions import AgentExtension

            class TestExtension(AgentExtension):
                @staticmethod
                def matches(node_type: str, name: str) -> bool:
                    return node_type == "function" and name.startswith("test_")

                @staticmethod
                def get_extension_data() -> dict:
                    return {
                        "extension_name": "TestAgent",
                        "custom_system_prompt": "You are a test runner.",
                    }
        """)
        )

        exts = load_extensions(models_dir)
        assert len(exts) == 1
        assert exts[0].matches("function", "test_foo") is True
        assert exts[0].matches("function", "calculate") is False
        data = exts[0].get_extension_data()
        assert data["extension_name"] == "TestAgent"

    def test_mtime_caching(self, tmp_path: Path):
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        ext_file = models_dir / "test_agent.py"
        ext_file.write_text(
            textwrap.dedent("""\
            from remora.extensions import AgentExtension

            class TestExtension(AgentExtension):
                @staticmethod
                def matches(node_type: str, name: str) -> bool:
                    return False

                @staticmethod
                def get_extension_data() -> dict:
                    return {"extension_name": "Test"}
        """)
        )

        exts1 = load_extensions(models_dir)
        exts2 = load_extensions(models_dir)
        # Same objects returned from cache (same list contents)
        assert len(exts1) == len(exts2) == 1

    def test_load_order_alphabetical(self, tmp_path: Path):
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        for fname in ["50_generic.py", "00_specific.py"]:
            (models_dir / fname).write_text(
                textwrap.dedent(f"""\
                from remora.extensions import AgentExtension

                class Ext_{fname.split(".")[0]}(AgentExtension):
                    @staticmethod
                    def matches(node_type: str, name: str) -> bool:
                        return True

                    @staticmethod
                    def get_extension_data() -> dict:
                        return {{"extension_name": "{fname}"}}
            """)
            )

        exts = load_extensions(models_dir)
        assert len(exts) == 2
        # 00_specific should come first (alphabetical by filename)
        assert exts[0].get_extension_data()["extension_name"] == "00_specific.py"


class TestExtensionMatchesBackwardCompat:
    """Old 2-arg extensions still work via extension_matches() fallback."""

    def test_old_style_extension_works_via_helper(self, tmp_path: Path):
        """extension_matches() falls back to 2-arg call for old-style extensions."""
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        ext_file = models_dir / "old_style.py"
        ext_file.write_text(
            textwrap.dedent("""\
            from remora.extensions import AgentExtension

            class OldStyleExtension(AgentExtension):
                @staticmethod
                def matches(node_type: str, name: str) -> bool:
                    return name == "old_func"

                @staticmethod
                def get_extension_data() -> dict:
                    return {"extension_name": "OldStyle"}
        """)
        )

        from remora.extensions import _cache

        _cache.clear()

        exts = load_extensions(models_dir)
        assert len(exts) == 1

        # extension_matches should fall back to 2-arg call
        assert extension_matches(exts[0], "function", "old_func", file_path="x.py", source_code="...") is True
        assert extension_matches(exts[0], "function", "other", file_path="x.py", source_code="...") is False
