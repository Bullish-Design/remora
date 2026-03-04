"""Tests for __main__.py entry point and launch.sh."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest


class TestMainModule:
    """Verify __main__.py module structure and arg parsing."""

    def test_main_file_exists(self) -> None:
        p = Path(__file__).parent.parent / "remora_demo" / "web" / "graph" / "__main__.py"
        assert p.exists()

    def test_main_has_argparse(self) -> None:
        source = (Path(__file__).parent.parent / "remora_demo" / "web" / "graph" / "__main__.py").read_text()
        assert "argparse" in source
        assert "--port" in source
        assert "--host" in source
        assert "--db" in source
        assert "--poll-interval" in source
        assert "--verbose" in source

    def test_main_prints_banner(self) -> None:
        source = (Path(__file__).parent.parent / "remora_demo" / "web" / "graph" / "__main__.py").read_text()
        assert "Remora Graph Viewer" in source

    def test_main_warns_missing_db(self) -> None:
        source = (Path(__file__).parent.parent / "remora_demo" / "web" / "graph" / "__main__.py").read_text()
        assert "DB not found" in source

    def test_main_uses_asyncio_run(self) -> None:
        source = (Path(__file__).parent.parent / "remora_demo" / "web" / "graph" / "__main__.py").read_text()
        assert "asyncio.run" in source

    def test_main_defers_stario_import(self) -> None:
        """Stario import is inside _serve(), not at module top level."""
        source = (Path(__file__).parent.parent / "remora_demo" / "web" / "graph" / "__main__.py").read_text()
        # The top-level imports should NOT include stario
        lines_before_def = []
        for line in source.splitlines():
            if line.startswith("def ") or line.startswith("async def "):
                break
            lines_before_def.append(line)
        top_section = "\n".join(lines_before_def)
        assert "stario" not in top_section

    def test_main_importable(self) -> None:
        """Module can be imported without stario (lazy import)."""
        # This should work because stario is only imported inside _serve()
        from remora_demo.web.graph.__main__ import main

        assert callable(main)


class TestLaunchScript:
    """Verify launch.sh structure."""

    def test_launch_sh_exists(self) -> None:
        p = Path(__file__).parent.parent / "remora_demo" / "launch.sh"
        assert p.exists()

    def test_launch_sh_is_executable(self) -> None:
        import os

        p = Path(__file__).parent.parent / "remora_demo" / "launch.sh"
        assert os.access(p, os.X_OK)

    def test_launch_sh_has_shebang(self) -> None:
        p = Path(__file__).parent.parent / "remora_demo" / "launch.sh"
        first_line = p.read_text().splitlines()[0]
        assert first_line.startswith("#!/")

    def test_launch_sh_runs_module(self) -> None:
        source = (Path(__file__).parent.parent / "remora_demo" / "launch.sh").read_text()
        assert "python -m remora_demo.web.graph" in source
