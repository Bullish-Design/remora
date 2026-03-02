"""Tests for AgentExtension base class and loader."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from remora.extensions import AgentExtension, load_extensions


class TestAgentExtensionBase:
    def test_base_matches_returns_false(self):
        assert AgentExtension.matches("function", "foo") is False

    def test_base_get_extension_data_returns_empty(self):
        data = AgentExtension.get_extension_data()
        assert data == {}


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
