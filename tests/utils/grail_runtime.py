"""Shared Grail runtime test harness."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any


def load_script(path: Path, grail_dir: Path | None = None):
    """Load a .pym script via grail.load()."""
    import grail

    return grail.load(path, grail_dir=grail_dir)


def run_script(
    path: Path,
    inputs: dict[str, Any] | None,
    externals: dict[str, Any],
    files: dict[str, Any] | None = None,
    grail_dir: Path | None = None,
) -> dict[str, Any]:
    script = load_script(path, grail_dir=grail_dir)
    if inputs is None:
        return script.run_sync(externals=externals, files=files or {})
    return script.run_sync(inputs=inputs, externals=externals, files=files or {})


def assert_artifacts(grail_dir: Path, script_name: str) -> None:
    base = grail_dir / script_name
    assert (base / "check.json").exists(), f"Missing check.json for {script_name}"
    assert (base / "monty_code.py").exists(), f"Missing monty_code.py for {script_name}"
    assert (base / "stubs.pyi").exists(), f"Missing stubs.pyi for {script_name}"


def build_file_externals(
    root: Path,
    *,
    run_command: Callable[[str, list[str]], dict[str, Any]] | None = None,
    include_read_file: bool = True,
    include_write_file: bool = True,
    include_file_exists: bool = True,
    include_list_dir: bool = False,
) -> dict[str, Any]:
    externals: dict[str, Any] = {}

    if include_read_file:

        async def read_file(path: str) -> str:
            return (root / path).read_text(encoding="utf-8")

        externals["read_file"] = read_file

    if include_write_file:

        async def write_file(path: str, content: str) -> bool:
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return True

        externals["write_file"] = write_file

    if include_file_exists:

        async def file_exists(path: str) -> bool:
            return (root / path).exists()

        externals["file_exists"] = file_exists

    if include_list_dir:

        async def list_dir(path: str = ".") -> list[str]:
            directory = root / path
            if not directory.exists():
                return []
            return [entry.name for entry in directory.iterdir()]

        externals["list_dir"] = list_dir

    if run_command is not None:

        async def run_command_external(cmd: str, args: list[str]) -> dict[str, Any]:
            return run_command(cmd, args)

        externals["run_command"] = run_command_external
    else:

        async def run_command_external(cmd: str, args: list[str]) -> dict[str, Any]:
            import asyncio
            import subprocess
            process = await asyncio.create_subprocess_exec(
                cmd,
                *args,
                cwd=root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()
            return {
                "exit_code": process.returncode,
                "stdout": stdout.decode("utf-8") if stdout else "",
                "stderr": stderr.decode("utf-8") if stderr else "",
            }

        externals["run_command"] = run_command_external

    import json
    async def run_json_command(cmd: str, args: list[str]) -> Any:
        result = await externals["run_command"](cmd, args)
        stdout = str(result.get("stdout", ""))
        try:
            if not stdout.strip():
                return []
            return json.loads(stdout)
        except json.JSONDecodeError:
            return {
                "error": "Failed to parse JSON", 
                "stdout": stdout, 
                "stderr": str(result.get("stderr", "")),
                "exit_code": int(result.get("exit_code", 0) or 0)
            }
            
    externals["run_json_command"] = run_json_command

    return externals
