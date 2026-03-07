"""Workspace CLI commands.

Provides CLI commands for inspecting and managing Cairn workspaces.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import click

from remora.workspace.inspector import RemoraWorkspaceInspector


@click.group()
def workspace() -> None:
    """Workspace inspection and management commands."""
    pass


@workspace.command("stats")
@click.argument("workspace_path", type=click.Path(resolve_path=True))
def workspace_stats(workspace_path: str) -> None:
    """Show workspace statistics.

    WORKSPACE_PATH is the path to the workspace .db file.
    """

    async def _stats() -> None:
        async with await RemoraWorkspaceInspector.open(workspace_path) as inspector:
            stats = await inspector.stats()
            click.echo(inspector.format_stats(stats))

    asyncio.run(_stats())


@workspace.command("tree")
@click.argument("workspace_path", type=click.Path(resolve_path=True))
@click.option("--path", "-p", default="/", help="Root path for tree (default: /)")
@click.option("--depth", "-d", default=-1, type=int, help="Max depth (-1 for unlimited)")
def workspace_tree(workspace_path: str, path: str, depth: int) -> None:
    """Show workspace directory tree.

    WORKSPACE_PATH is the path to the workspace .db file.
    """

    async def _tree() -> None:
        async with await RemoraWorkspaceInspector.open(workspace_path) as inspector:
            tree = await inspector.tree(path, max_depth=depth)
            click.echo(tree)

    asyncio.run(_tree())


@workspace.command("ls")
@click.argument("workspace_path", type=click.Path(resolve_path=True))
@click.option("--path", "-p", default="/", help="Directory path to list (default: /)")
def workspace_ls(workspace_path: str, path: str) -> None:
    """List workspace directory contents.

    WORKSPACE_PATH is the path to the workspace .db file.
    """

    async def _ls() -> None:
        async with await RemoraWorkspaceInspector.open(workspace_path) as inspector:
            entries = await inspector.list_dir(path)
            if not entries:
                click.echo(f"Directory '{path}' is empty or does not exist.")
            else:
                for entry in sorted(entries):
                    click.echo(entry)

    asyncio.run(_ls())


@workspace.command("cat")
@click.argument("workspace_path", type=click.Path(resolve_path=True))
@click.argument("file_path")
def workspace_cat(workspace_path: str, file_path: str) -> None:
    """Read file contents from workspace.

    WORKSPACE_PATH is the path to the workspace .db file.
    FILE_PATH is the path within the workspace.
    """

    async def _cat() -> str:
        async with await RemoraWorkspaceInspector.open(workspace_path) as inspector:
            return await inspector.read_file(file_path)

    try:
        content = asyncio.run(_cat())
    except FileNotFoundError:
        raise click.ClickException(f"File not found: {file_path}")
    click.echo(content)


@workspace.command("kv-list")
@click.argument("workspace_path", type=click.Path(resolve_path=True))
@click.option("--prefix", "-p", default="", help="Filter keys by prefix")
def workspace_kv_list(workspace_path: str, prefix: str) -> None:
    """List KV store keys.

    WORKSPACE_PATH is the path to the workspace .db file.
    """

    async def _kv_list() -> None:
        async with await RemoraWorkspaceInspector.open(workspace_path) as inspector:
            keys = await inspector.get_kv_keys(prefix)
            if not keys:
                click.echo("No keys found.")
            else:
                click.echo(f"Keys ({len(keys)}):")
                for key in sorted(keys):
                    click.echo(f"  {key}")

    asyncio.run(_kv_list())


@workspace.command("kv-get")
@click.argument("workspace_path", type=click.Path(resolve_path=True))
@click.argument("key")
def workspace_kv_get(workspace_path: str, key: str) -> None:
    """Get value from KV store.

    WORKSPACE_PATH is the path to the workspace .db file.
    KEY is the KV store key.
    """
    import json

    async def _kv_get():
        async with await RemoraWorkspaceInspector.open(workspace_path) as inspector:
            return await inspector.get_kv_value(key)

    value = asyncio.run(_kv_get())
    if value is None:
        raise click.ClickException(f"Key not found: {key}")
    # Pretty print JSON-serializable values
    if isinstance(value, (dict, list)):
        click.echo(json.dumps(value, indent=2))
    else:
        click.echo(value)


@workspace.command("sync")
@click.argument("disk_dir", type=click.Path(exists=True, resolve_path=True))
@click.argument("workspace_path", type=click.Path(resolve_path=True))
@click.option("--dry-run", is_flag=True, help="Preview changes without applying")
@click.option("--delete", "include_deleted", is_flag=True, help="Also remove workspace files absent on disk")
@click.option("--prefix", "-p", default="/", help="Workspace path prefix (default: /)")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
def workspace_sync(
    disk_dir: str,
    workspace_path: str,
    dry_run: bool,
    include_deleted: bool,
    prefix: str,
    yes: bool,
) -> None:
    """Sync disk directory changes into a workspace.

    DISK_DIR is the local directory to sync from.
    WORKSPACE_PATH is the path to the workspace .db file.
    """

    async def _sync() -> None:
        from cairn.runtime.workspace_manager import open_workspace as cairn_open_workspace

        from remora.core.agents.workspace import AgentWorkspace
        from remora.workspace.sync import WorkspaceSync

        ws = await cairn_open_workspace(Path(workspace_path), readonly=False)
        try:
            agent_ws = AgentWorkspace(ws, agent_id="cli-sync")
            sync_util = WorkspaceSync(agent_ws, Path(disk_dir))

            # Scan
            changes = await sync_util.scan_disk_changes(Path(disk_dir), prefix)
            if include_deleted:
                deleted = await sync_util.scan_deleted(Path(disk_dir), prefix)
                changes.extend(deleted)

            if not changes:
                click.echo("No changes to sync.")
                return

            click.echo("Changes to sync:")
            markers = {"added": "+", "modified": "M", "deleted": "-"}
            for change in changes:
                click.echo(f"  [{markers[change.change_type]}] {change.path}")

            if dry_run:
                click.echo(f"\nDry run: {len(changes)} change(s) would be applied.")
                return

            if not yes:
                if not click.confirm(f"Apply {len(changes)} change(s)?"):
                    click.echo("Aborted.")
                    return

            result = await sync_util.sync_from_disk(
                Path(disk_dir),
                prefix,
                include_deleted=include_deleted,
            )
            click.echo(f"Synced {len(result.synced)} file(s).")
            if result.errors:
                click.echo("Errors:")
                for path, error in result.errors:
                    click.echo(f"  {path}: {error}")
        finally:
            if hasattr(ws, "close"):
                await ws.close()

    asyncio.run(_sync())


@workspace.command("sandbox")
@click.argument("workspace_path", type=click.Path(resolve_path=True))
@click.argument("command")
@click.option("--image", default="python:3.12-slim", help="Container image")
@click.option("--memory", default="512m", help="Memory limit (e.g., 512m, 1g)")
@click.option("--cpus", default=1.0, type=float, help="CPU limit")
@click.option("--timeout", default=300.0, type=float, help="Timeout in seconds")
@click.option("--network", is_flag=True, help="Enable network access")
@click.option("--sync-back", is_flag=True, help="Sync changes back to workspace after execution")
def workspace_sandbox(
    workspace_path: str,
    command: str,
    image: str,
    memory: str,
    cpus: float,
    timeout: float,
    network: bool,
    sync_back: bool,
) -> None:
    """Run a command in a sandboxed container with workspace files.

    WORKSPACE_PATH is the path to the workspace .db file.
    COMMAND is the shell command to execute in the container.
    """
    import tempfile

    async def _sandbox() -> None:
        from cairn.runtime.workspace_manager import open_workspace as cairn_open_workspace

        from remora.workspace.sandbox import SandboxConfig, WorkspaceSandbox

        ws = await cairn_open_workspace(Path(workspace_path), readonly=not sync_back)
        try:
            # Materialize workspace to temp directory
            with tempfile.TemporaryDirectory(prefix="remora-sandbox-") as tmp_dir:
                work_dir = Path(tmp_dir)
                await ws.materialize.to_disk(work_dir)

                config = SandboxConfig(
                    image=image,
                    memory_limit=memory,
                    cpu_limit=cpus,
                    timeout=timeout,
                    network=network,
                )
                sandbox = WorkspaceSandbox(work_dir, config=config)
                result = await sandbox.exec(command)

                # Output results
                if result.stdout:
                    click.echo(result.stdout, nl=False)
                if result.stderr:
                    click.echo(result.stderr, nl=False, err=True)

                if result.timed_out:
                    click.echo(f"\nExecution timed out after {timeout}s", err=True)

                # Sync back if requested
                if sync_back and result.exit_code == 0:
                    from remora.core.agents.workspace import AgentWorkspace
                    from remora.workspace.sync import WorkspaceSync

                    agent_ws = AgentWorkspace(ws, agent_id="cli-sandbox")
                    sync_util = WorkspaceSync(agent_ws, work_dir)
                    sync_result = await sync_util.sync_from_disk(work_dir, "/")
                    if sync_result.synced:
                        click.echo(f"\nSynced {len(sync_result.synced)} file(s) back to workspace.")
                    if sync_result.errors:
                        click.echo("Sync errors:", err=True)
                        for path, error in sync_result.errors:
                            click.echo(f"  {path}: {error}", err=True)

                if result.exit_code != 0:
                    raise SystemExit(result.exit_code)
        finally:
            if hasattr(ws, "close"):
                await ws.close()

    asyncio.run(_sandbox())


@workspace.command("find")
@click.argument("workspace_path", type=click.Path(resolve_path=True))
@click.argument("pattern")
@click.option("--path", "-p", default="/", help="Search root (default: /)")
def workspace_find(workspace_path: str, pattern: str, path: str) -> None:
    """Find files matching a pattern.

    WORKSPACE_PATH is the path to the workspace .db file.
    PATTERN is a glob pattern (e.g., "*.py", "src/**/*.ts").
    """
    import fnmatch

    async def _find() -> None:
        async with await RemoraWorkspaceInspector.open(workspace_path) as inspector:
            # Get all files recursively and filter by pattern
            matches = []

            async def search_dir(dir_path: str) -> None:
                entries = await inspector.list_dir(dir_path)
                for entry in entries:
                    full_path = f"{dir_path.rstrip('/')}/{entry}"
                    if fnmatch.fnmatch(entry, pattern) or fnmatch.fnmatch(full_path, pattern):
                        matches.append(full_path)
                    # Check if it's a directory by trying to list it
                    try:
                        sub_entries = await inspector.list_dir(full_path)
                        if sub_entries is not None:
                            await search_dir(full_path)
                    except Exception:
                        pass  # Not a directory

            await search_dir(path)

            if not matches:
                click.echo(f"No files matching '{pattern}' found.")
            else:
                for match in sorted(matches):
                    click.echo(match)

    asyncio.run(_find())


@workspace.command("validate")
@click.argument("workspace_path", type=click.Path(resolve_path=True))
@click.option("--checks", "-c", multiple=True, default=["syntax"], help="Checks to run (syntax, types, tests, lint)")
@click.option("--all-checks", is_flag=True, help="Run all checks (syntax, types, tests, lint)")
@click.option("--image", default="python:3.12-slim", help="Container image")
@click.option("--timeout", default=120.0, type=float, help="Timeout per check in seconds")
def workspace_validate(
    workspace_path: str,
    checks: tuple[str, ...],
    all_checks: bool,
    image: str,
    timeout: float,
) -> None:
    """Validate workspace code quality in a sandboxed container.

    WORKSPACE_PATH is the path to the workspace .db file.
    Runs configurable checks (syntax, types, tests, lint).
    """
    import tempfile

    async def _validate() -> None:
        from cairn.runtime.workspace_manager import open_workspace as cairn_open_workspace

        from remora.workspace.sandbox import SandboxConfig, WorkspaceSandbox
        from remora.workspace.validation import WorkspaceValidator

        check_list = list(WorkspaceValidator.DEFAULT_CHECKS) if all_checks else list(checks)

        ws = await cairn_open_workspace(Path(workspace_path), readonly=True)
        try:
            with tempfile.TemporaryDirectory(prefix="remora-validate-") as tmp_dir:
                work_dir = Path(tmp_dir)
                await ws.materialize.to_disk(work_dir)

                config = SandboxConfig(image=image, timeout=timeout)
                sandbox = WorkspaceSandbox(work_dir, config=config)
                validator = WorkspaceValidator(sandbox, checks=check_list)

                click.echo(f"Running checks: {', '.join(check_list)}")
                result = await validator.validate()

                for check in result.checks:
                    status = "PASS" if check.passed else "FAIL"
                    click.echo(f"  [{status}] {check.name} ({check.duration:.2f}s)")
                    if not check.passed and check.error:
                        for line in check.error.split("\n")[:10]:
                            click.echo(f"        {line}")

                click.echo(f"\n{result.summary()}")

                if not result.all_passed:
                    raise SystemExit(1)
        finally:
            if hasattr(ws, "close"):
                await ws.close()

    asyncio.run(_validate())


__all__ = ["workspace"]
