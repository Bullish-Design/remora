"""Cairn CLI bridge for executing Grail scripts."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from remora.config import CairnConfig


class CairnError(RuntimeError):
    pass


class CairnCLIClient:
    def __init__(self, config: CairnConfig) -> None:
        self.command = config.command
        self.home = config.home
        self.timeout = config.timeout

    async def run_pym(self, path: Path, workspace_id: str, inputs: dict[str, Any]) -> dict[str, Any] | str:
        env = os.environ.copy()
        if self.home is not None:
            env["CAIRN_HOME"] = str(self.home)
        proc = await asyncio.create_subprocess_exec(
            self.command,
            "run",
            str(path),
            "--workspace",
            workspace_id,
            "--inputs",
            json.dumps(inputs),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self.timeout)
        except asyncio.TimeoutError as exc:
            proc.kill()
            raise CairnError(f"Cairn run timed out after {self.timeout}s") from exc
        if proc.returncode != 0:
            message = stderr.decode("utf-8", errors="replace").strip()
            raise CairnError(message or f"Cairn exit code {proc.returncode}")
        output = stdout.decode("utf-8", errors="replace").strip()
        if not output:
            return {}
        try:
            return json.loads(output)
        except json.JSONDecodeError:
            return output
