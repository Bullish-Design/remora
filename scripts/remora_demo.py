"""Run a small Remora demo workload for the dashboard."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
from pathlib import Path
import shutil
import subprocess
import sys
import os
import contextlib
from typing import Any

import typer

from remora.config import CairnConfig, OperationConfig, RemoraConfig, load_config
from remora.discovery import CSTNode, PydantreeDiscoverer
from remora.events import build_event_emitter
from remora.runner import FunctionGemmaRunner
from remora.subagent import load_subagent_definition

app = typer.Typer(help="Run a small Remora demo workload.")


@dataclass
class DemoCairnClient:
    base_dir: Path
    work_dir: Path
    _workspace_map: dict[str, tuple[Path, str | None]] = field(default_factory=dict)

    def register_workspace(self, workspace_id: str, target_relpath: Path, node_text: str | None) -> None:
        self._workspace_map[workspace_id] = (target_relpath, node_text)

    async def run_pym(self, path: Any, workspace_id: str, inputs: dict[str, Any]) -> dict[str, Any]:
        workspace_dir = self._ensure_workspace(workspace_id)
        target_relpath, node_text = self._workspace_map.get(workspace_id, (None, None))
        env = os.environ.copy()
        env["REMORA_WORKSPACE_DIR"] = str(workspace_dir)
        env["REMORA_WORKSPACE_ID"] = workspace_id
        if target_relpath is not None:
            env["REMORA_TARGET_FILE"] = str(target_relpath)
        if node_text:
            env["REMORA_NODE_TEXT"] = node_text
        env["REMORA_INPUT"] = json.dumps(inputs)

        completed = subprocess.run(
            [sys.executable, str(path)],
            cwd=str(workspace_dir),
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        if completed.returncode != 0:
            return {"error": completed.stderr.strip() or f"tool exit code {completed.returncode}"}
        output = completed.stdout.strip()
        if not output:
            return {}
        try:
            return json.loads(output)
        except json.JSONDecodeError:
            return {"result": output}

    def _ensure_workspace(self, workspace_id: str) -> Path:
        workspace_dir = self.work_dir / workspace_id
        if workspace_dir.exists():
            shutil.rmtree(workspace_dir)
        shutil.copytree(self.base_dir, workspace_dir, ignore=shutil.ignore_patterns(".remora_demo"))
        remora_dir = workspace_dir / ".remora"
        remora_dir.mkdir(parents=True, exist_ok=True)
        target_relpath, node_text = self._workspace_map.get(workspace_id, (None, None))
        if target_relpath is not None:
            (remora_dir / "target_file").write_text(str(target_relpath), encoding="utf-8")
        if node_text:
            (remora_dir / "node_text").write_text(node_text, encoding="utf-8")
        return workspace_dir


def _demo_root() -> Path:
    return Path(__file__).resolve().parents[1] / "training" / "demo_project"


def _build_demo_config(base: RemoraConfig, demo_root: Path) -> RemoraConfig:
    lint_op = base.operations.get("lint", OperationConfig(subagent="lint/lint_subagent.yaml"))
    docstring_op = base.operations.get(
        "docstring",
        OperationConfig.model_validate({"subagent": "docstring/docstring_subagent.yaml", "style": "google"}),
    )
    type_check_op = lint_op.model_copy()
    operations = {
        "lint": lint_op,
        "docstring": docstring_op,
        "type_check": type_check_op,
    }
    return base.model_copy(
        update={
            "operations": operations,
            "cairn": CairnConfig(max_concurrent_agents=1),
        }
    )


def _collect_nodes(config: RemoraConfig, demo_root: Path) -> list[CSTNode]:
    discoverer = PydantreeDiscoverer(
        [demo_root],
        config.discovery.language,
        config.discovery.query_pack,
    )
    return discoverer.discover()


async def _run_once(config: RemoraConfig, demo_root: Path) -> None:
    event_emitter = build_event_emitter(config.event_stream)
    watch_task = asyncio.create_task(event_emitter.watch())

    demo_work_dir = demo_root / ".remora_demo" / "workspaces"
    demo_work_dir.mkdir(parents=True, exist_ok=True)
    cairn_client = DemoCairnClient(base_dir=demo_root, work_dir=demo_work_dir)

    try:
        nodes = _collect_nodes(config, demo_root)
        operations = list(config.operations.keys())
        for node in nodes:
            for operation in operations:
                op_config = config.operations[operation]
                definition_path = config.agents_dir / op_config.subagent
                definition = load_subagent_definition(definition_path, agents_dir=config.agents_dir)
                workspace_id = f"{operation}-{node.node_id}"
                target_relpath = node.file_path.relative_to(demo_root)
                cairn_client.register_workspace(workspace_id, target_relpath, node.text)
                runner = FunctionGemmaRunner(
                    definition=definition,
                    node=node,
                    workspace_id=workspace_id,
                    cairn_client=cairn_client,
                    server_config=config.server,
                    runner_config=config.runner,
                    adapter_name=op_config.model_id,
                    event_emitter=event_emitter,
                )
                try:
                    await runner.run()
                except Exception as exc:
                    event_emitter.emit(
                        {
                            "event": "agent_error",
                            "agent_id": workspace_id,
                            "node_id": node.node_id,
                            "operation": operation,
                            "phase": "run",
                            "error": str(exc),
                        }
                    )
    finally:
        watch_task.cancel()
        event_emitter.close()
        with contextlib.suppress(asyncio.CancelledError):
            await watch_task


@app.command()
def main(
    continuous: bool = typer.Option(False, "--continuous", "-c"),
    sleep_seconds: float = typer.Option(2.0, "--sleep"),
) -> None:
    demo_root = _demo_root()
    base_config = load_config(None, overrides=None)
    config = _build_demo_config(base_config, demo_root)

    async def _runner() -> None:
        if not continuous:
            await _run_once(config, demo_root)
            return
        while True:
            await _run_once(config, demo_root)
            await asyncio.sleep(sleep_seconds)

    asyncio.run(_runner())


if __name__ == "__main__":
    app()
