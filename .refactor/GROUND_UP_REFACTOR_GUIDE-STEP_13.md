# Implementation Guide for Step 13: CLI Integration

## Overview

This step creates unified CLI entry points that tie together discovery, execution, indexer, and dashboard. This is the final integration step that provides user-facing commands for the refactored Remora system.

This implements Idea 3 (Split the Hub Into Indexer and Dashboard) and Step 13 from the recommended implementation order in the design document.

## Contract Touchpoints
- CLI loads `RemoraConfig` once and wires a shared `EventBus` instance.
- Entry points are `remora`, `remora-index`, `remora-dashboard`.

## Done Criteria
- [ ] Each CLI command starts and exits cleanly with `--help`.
- [ ] Core CLI runs discovery → graph → executor using config slices.
- [ ] Indexer and dashboard CLIs use the same `RemoraConfig` fields.

## Current State (What You're Replacing)

The current CLI is fragmented across multiple files:

- `src/remora/cli.py` - Main CLI with config, metrics, and list-agents commands (uses click/typer)
- `src/remora/__main__.py` - Simple module entry point
- `src/remora/hub/cli.py` - Hub daemon CLI with start/status/stop commands (uses click)

Current entry points in `pyproject.toml`:
```toml
remora = "remora.cli:app"
remora-hub = "remora.hub.cli:main"
```

## Target State

Three unified entry points:

| Command | Entry Point | Purpose |
|---------|-------------|---------|
| `remora` | `remora.cli:app` | Main CLI: discover, run |
| `remora-index` | `remora.indexer.cli:app` | Indexer daemon CLI |
| `remora-dashboard` | `remora.dashboard.cli:app` | Dashboard web server CLI |

## Prerequisites

Before implementing this step, ensure these modules exist from previous steps:

1. **Step 5** - `remora/config.py` - RemoraConfig with load_config()
2. **Step 6** - `remora/discovery.py` - discover() function
3. **Step 8** - `remora/graph.py` - build_graph() function
4. **Step 10** - `remora/executor.py` - GraphExecutor class
5. **Step 11** - `remora/indexer/` package - indexer module
6. **Step 12** - `remora/dashboard/` package - dashboard module

Verify these imports work:

```bash
python -c "from remora.config import load_config"
python -c "from remora.discovery import discover"
python -c "from remora.graph import build_graph"
python -c "from remora.executor import GraphExecutor"
python -c "from remora.indexer import IndexerDaemon"
python -c "from remora.dashboard import create_app"
```

## Implementation Steps

### Step 1: Create Main CLI (remora)

**File:** `src/remora/cli.py`

Replace the entire file content:

```python
"""Command-line interface for Remora."""

from __future__ import annotations

import asyncio
import importlib.metadata
import json
from pathlib import Path
from typing import Any

import typer
import yaml
from rich.console import Console

from remora.config import load_config
from remora.discovery import discover, CSTNode
from remora.graph import build_graph, AgentNode
from remora.executor import GraphExecutor
from remora.event_bus import EventBus

app = typer.Typer(help="Remora - Code analysis agent framework")
console = Console()


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(importlib.metadata.version("remora"))
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(None, "--version", callback=_version_callback, is_eager=True),
) -> None:
    """Remora - Code analysis agent framework."""
    pass


@app.command()
def run(
    paths: list[str] = typer.Argument(["src/"], help="Paths to scan"),
    bundles: str = typer.Option("agents/", help="Path to agent bundles"),
    config: Path = typer.Option("remora.yaml", help="Config file"),
    max_concurrency: int = typer.Option(4, "--concurrency", "-c", help="Max concurrent agents"),
) -> None:
    """Run analysis on source code."""
    try:
        cfg = load_config(config)
    except FileNotFoundError:
        console.print(f"[red]Error: Config file '{config}' not found[/red]")
        raise typer.Exit(code=1)
    except Exception as e:
        console.print(f"[red]Error loading config: {e}[/red]")
        raise typer.Exit(code=1)

    console.print(f"[cyan]Discovering nodes in: {paths}[/cyan]")
    nodes = discover(
        paths=[Path(p) for p in paths],
        languages=cfg.discovery.languages if hasattr(cfg, 'discovery') else None,
    )
    console.print(f"[green]Discovered {len(nodes)} nodes[/green]")

    console.print(f"[cyan]Building agent graph...[/cyan]")
    bundle_map = _load_bundle_mapping(cfg, bundles)
    graph = build_graph(nodes, bundle_map, cfg)
    console.print(f"[green]Built graph with {len(graph)} agents[/green]")

    console.print(f"[cyan]Executing graph (max {max_concurrency} concurrent)...[/cyan]")
    event_bus = EventBus()
    executor = GraphExecutor(cfg.execution if hasattr(cfg, 'execution') else None, event_bus)
    
    results = asyncio.run(executor.run(graph, cfg.workspace if hasattr(cfg, 'workspace') else None))
    
    completed = sum(1 for r in results.values() if r.success)
    console.print(f"[green]Completed {completed}/{len(results)} agents successfully[/green]")

    for agent_id, result in results.items():
        if not result.success:
            console.print(f"[yellow]  {agent_id}: {result.error or 'failed'}[/yellow]")


@app.command()
def discover(
    paths: list[str] = typer.Argument(["src/"], help="Paths to scan"),
    output: Path = typer.Option("-", help="Output file (use - for stdout)"),
    languages: list[str] | None = typer.Option(None, "--language", "-l", help="Languages to scan"),
) -> None:
    """Discover code nodes without executing."""
    nodes = discover(
        paths=[Path(p) for p in paths],
        languages=languages,
    )

    output_data = [{
        "node_id": n.node_id,
        "node_type": n.node_type,
        "name": n.name,
        "file_path": n.file_path,
        "start_line": n.start_line,
        "end_line": n.end_line,
    } for n in nodes]

    json_output = json.dumps(output_data, indent=2)
    
    if str(output) == "-" or str(output) == "/dev/stdout":
        typer.echo(json_output)
    else:
        output.write_text(json_output)
        console.print(f"[green]Wrote {len(nodes)} nodes to {output}[/green]")


@app.command()
def config(
    config_path: Path = typer.Option("remora.yaml", "--config", "-c", help="Config file"),
    output_format: str = typer.Option("yaml", "--format", "-f", help="Output format: yaml or json"),
) -> None:
    """Show current configuration."""
    try:
        cfg = load_config(config_path)
    except FileNotFoundError:
        console.print(f"[red]Error: Config file '{config}' not found[/red]")
        raise typer.Exit(code=1)
    except Exception as e:
        console.print(f"[red]Error loading config: {e}[/red]")
        raise typer.Exit(code=1)

    if output_format.lower() == "json":
        typer.echo(cfg.to_json())
    else:
        typer.echo(cfg.to_yaml())


def _load_bundle_mapping(config, bundles_path: str) -> dict[str, Path]:
    """Load bundle path mapping from config."""
    mapping = {}
    base = Path(bundles_path)
    
    if hasattr(config, 'bundles') and hasattr(config.bundles, 'mapping'):
        for node_type, bundle_name in config.bundles.mapping.items():
            mapping[node_type] = base / bundle_name
    
    return mapping


if __name__ == "__main__":
    app()
```

### Step 2: Create Indexer CLI

**File:** `src/remora/indexer/cli.py`

```python
"""CLI for the Remora indexer daemon."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

import typer
from rich.console import Console

from remora.indexer.daemon import IndexerDaemon

app = typer.Typer(help="Remora indexer - Background file indexing daemon")
console = Console()

logger = logging.getLogger(__name__)


@app.command()
def start(
    project_root: Path = typer.Option(Path.cwd(), "--project-root", "-p", help="Project root directory"),
    store_path: Path = typer.Option(None, "--store-path", "-s", help="Index store path"),
    watch_paths: list[str] = typer.Option(["src/"], "--watch", "-w", help="Paths to watch"),
    log_level: str = typer.Option("INFO", "--log-level", "-l", help="Logging level"),
    foreground: bool = typer.Option(True, "--foreground/--background", help="Run in foreground"),
) -> None:
    """Start the indexer daemon."""
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not foreground:
        _daemonize()

    store = Path(store_path) if store_path else project_root / ".remora" / "index"
    watch = [Path(p) for p in watch_paths]

    console.print(f"[cyan]Starting indexer daemon...[/cyan]")
    console.print(f"  Project root: {project_root}")
    console.print(f"  Store path: {store}")
    console.print(f"  Watch paths: {watch}")

    daemon = IndexerDaemon(
        project_root=project_root,
        store_path=store,
        watch_paths=watch,
    )

    try:
        asyncio.run(daemon.run())
    except KeyboardInterrupt:
        console.print("\n[yellow]Indexer stopped[/yellow]")


@app.command()
def status(
    project_root: Path = typer.Option(Path.cwd(), "--project-root", "-p", help="Project root directory"),
) -> None:
    """Check indexer status."""
    store_path = project_root / ".remora" / "index"
    pid_file = project_root / ".remora" / "indexer.pid"

    if not store_path.exists():
        console.print("[yellow]Indexer: not initialized[/yellow]")
        console.print("  Run 'remora-index start' to initialize")
        return

    daemon_running = False
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, 0)
            daemon_running = True
        except (ValueError, OSError):
            pass

    from fsdantic import Fsdantic
    from remora.indexer.store import NodeStateStore

    async def get_stats():
        workspace = await Fsdantic.open(path=str(store_path))
        store = NodeStateStore(workspace)
        stats = await store.stats()
        await workspace.close()
        return stats

    stats = asyncio.run(get_stats())

    console.print(f"[cyan]Indexer:[/cyan] {'running' if daemon_running else 'stopped'}")
    console.print(f"  Store: {store_path}")
    console.print(f"  Files indexed: {stats.get('files', 0)}")
    console.print(f"  Nodes indexed: {stats.get('nodes', 0)}")


@app.command()
def stop(
    project_root: Path = typer.Option(Path.cwd(), "--project-root", "-p", help="Project root directory"),
) -> None:
    """Stop the indexer daemon."""
    pid_file = project_root / ".remora" / "indexer.pid"

    if not pid_file.exists():
        console.print("[yellow]Indexer daemon not running[/yellow]")
        return

    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        console.print(f"[green]Sent SIGTERM to indexer daemon (PID {pid})[/green]")
    except ValueError:
        console.print("[red]Invalid PID file[/red]")
    except OSError as e:
        console.print(f"[red]Failed to stop daemon: {e}[/red]")


def _daemonize() -> None:
    """Daemonize the process (Unix only)."""
    if os.name != "posix":
        raise typer.ClickException("Background mode only supported on Unix")

    if os.fork() > 0:
        sys.exit(0)

    os.setsid()

    if os.fork() > 0:
        sys.exit(0)

    sys.stdin = open(os.devnull, "r")
    sys.stdout = open(os.devnull, "w")
    sys.stderr = open(os.devnull, "w")


if __name__ == "__main__":
    app()
```

### Step 3: Create Dashboard CLI

**File:** `src/remora/dashboard/cli.py`

```python
"""CLI for the Remora dashboard web server."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import typer
from rich.console import Console

from remora.dashboard.app import create_app

app = typer.Typer(help="Remora dashboard - Web interface for graph execution")
console = Console()

logger = logging.getLogger(__name__)


@app.command()
def start(
    host: str = typer.Option("0.0.0.0", "--host", "-h", help="Host to bind to"),
    port: int = typer.Option(8420, "--port", "-p", help="Port to bind to"),
    project_root: Path = typer.Option(Path.cwd(), "--project-root", help="Project root directory"),
    store_path: Path = typer.Option(None, "--store-path", "-s", help="Index store path"),
    log_level: str = typer.Option("INFO", "--log-level", "-l", help="Logging level"),
) -> None:
    """Start the dashboard web server."""
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    store = Path(store_path) if store_path else project_root / ".remora" / "index"

    console.print(f"[cyan]Starting dashboard...[/cyan]")
    console.print(f"  Host: {host}")
    console.print(f"  Port: {port}")
    console.print(f"  Store: {store}")

    import uvicorn
    from remora.dashboard.app import create_app
    
    app_instance = create_app(
        project_root=project_root,
        store_path=store,
    )
    
    uvicorn.run(
        app_instance,
        host=host,
        port=port,
        log_level=log_level.lower(),
    )


@app.command()
def config(
    project_root: Path = typer.Option(Path.cwd(), "--project-root", "-p", help="Project root directory"),
) -> None:
    """Show dashboard configuration."""
    from remora.config import load_config
    
    config_path = project_root / "remora.yaml"
    if not config_path.exists():
        console.print("[yellow]No remora.yaml found, using defaults[/yellow]")
        return
    
    cfg = load_config(config_path)
    
    dashboard_cfg = getattr(cfg, 'dashboard', None)
    if dashboard_cfg:
        console.print(f"[cyan]Dashboard config:[/cyan]")
        console.print(f"  Host: {getattr(dashboard_cfg, 'host', '0.0.0.0')}")
        console.print(f"  Port: {getattr(dashboard_cfg, 'port', 8420)}")
    else:
        console.print("[yellow]No dashboard config in remora.yaml[/yellow]")
        console.print("  Using defaults: host=0.0.0.0, port=8420")


if __name__ == "__main__":
    app()
```

### Step 4: Update __main__.py

**File:** `src/remora/__main__.py`

```python
"""Module entrypoint for `python -m remora`."""

from remora.cli import app

app()
```

### Step 5: Add indexer and dashboard package init files

**File:** `src/remora/indexer/__init__.py`

```python
"""Indexer package for Remora."""

from remora.indexer.daemon import IndexerDaemon
from remora.indexer.store import NodeStateStore

__all__ = ["IndexerDaemon", "NodeStateStore"]
```

**File:** `src/remora/dashboard/__init__.py`

```python
"""Dashboard package for Remora."""

from remora.dashboard.app import create_app

__all__ = ["create_app"]
```

### Step 6: Update pyproject.toml Entry Points

**File:** `pyproject.toml`

Update the `[project.scripts]` section:

```toml
[project.scripts]

remora = "remora.cli:app"
remora-index = "remora.indexer.cli:app"
remora-dashboard = "remora.dashboard.cli:app"
```

Remove the old entry point:
```toml
remora-hub = "remora.hub.cli:main"
```

### Step 7: Verify CLI Commands Work

After installing the package:

```bash
pip install -e .

remora --help
remora discover src/
remora config
remora-index --help
remora-index status
remora-dashboard --help
```

Expected output:

```
$ remora --help
 Usage: remora [OPTIONS] COMMAND [ARGS]...
 
 Remora - Code analysis agent framework

 Options:
   --version  Show the version.
   --help     Show this message.

 Commands:
   config     Show current configuration.
   discover   Discover code nodes without executing.
   run        Run analysis on source code.
```

```
$ remora-index --help
 Usage: remora-index [OPTIONS] COMMAND [ARGS]...
 
 Remora indexer - Background file indexing daemon

 Options:
   --help  Show this message.

 Commands:
   start    Start the indexer daemon.
   status   Check indexer status.
   stop     Stop the indexer daemon.
```

```
$ remora-dashboard --help
 Usage: remora-dashboard [OPTIONS] COMMAND [ARGS]...
 
 Remora dashboard - Web interface for graph execution

 Options:
   --help  Show this message.

 Commands:
   config   Show dashboard configuration.
   start    Start the dashboard web server.
```

## Common Pitfalls

1. **asyncio.run isolation** - Make sure `asyncio.run()` is called in the CLI commands, not in library code. The CLI is the async boundary.

2. **Entry point matching** - The entry point name in `pyproject.toml` must match the function being exported:
   - `remora-index = "remora.indexer.cli:app"` - NOT `main`
   - `remora-dashboard = "remora.dashboard.cli:app"` - NOT `main`

3. **Missing __init__.py** - The indexer and dashboard packages need `__init__.py` files or they'll fail to import.

4. **typer vs click** - The existing hub CLI uses click, but this guide uses typer for consistency. Make sure not to mix them in the same app.

5. **Config attribute access** - Use `hasattr()` when accessing optional config sections, as the config structure may vary.

6. **Store path resolution** - The indexer store path should default to `.remora/index` within the project root, not an absolute path.

## Configuration Requirements

The CLI expects these config sections in `remora.yaml`:

```yaml
discovery:
  paths: ["src/"]
  languages: ["python", "markdown"]

bundles:
  path: "agents/"
  mapping:
    function: lint
    class: docstring
    file: test

execution:
  max_concurrency: 4
  error_policy: skip_downstream
  timeout: 300

workspace:
  base_path: ".remora/workspaces"

dashboard:
  host: "0.0.0.0"
  port: 8420
```

## Testing Checklist

- [ ] `remora --help` displays all commands
- [ ] `remora discover src/` outputs JSON to stdout
- [ ] `remora discover src/ -o nodes.json` writes to file
- [ ] `remora config` outputs current config
- [ ] `remora run src/` executes discovery and graph
- [ ] `remora-index --help` displays indexer commands
- [ ] `remora-index start` starts the daemon
- [ ] `remora-index status` shows indexer stats
- [ ] `remora-index stop` stops the daemon
- [ ] `remora-dashboard --help` displays dashboard commands
- [ ] `remora-dashboard start` starts the web server
- [ ] `remora-dashboard config` shows dashboard config
- [ ] Entry points work after `pip install -e .`

## Files to Create/Modify

| File | Action |
|------|--------|
| `src/remora/cli.py` | Rewrite completely |
| `src/remora/__main__.py` | Update import |
| `src/remora/indexer/__init__.py` | Create |
| `src/remora/indexer/cli.py` | Create |
| `src/remora/dashboard/__init__.py` | Create |
| `src/remora/dashboard/cli.py` | Create |
| `pyproject.toml` | Update entry points |

## Dependencies

- typer (already in dependencies)
- rich (already in dependencies)
- uvicorn (for dashboard)
- All remora modules from previous steps
