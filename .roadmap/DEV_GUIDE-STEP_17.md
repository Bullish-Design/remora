# DEV GUIDE STEP 17: CLI + Watch Mode

## Goal
Deliver the complete end-to-end CLI experience: `analyze`, `watch`, `config`, and `list-agents` commands, all wired to the real analysis pipeline. Add reactive watch mode with debouncing.

## Why This Matters
The CLI is the only interface most users will interact with. It must wire every layer together (config → discovery → coordinator → runners → results → accept/reject) and handle the user's intent cleanly. `list-agents` is particularly important for transparency: users need to see which GGUF models are loaded and their status.

## Implementation Checklist
- Wire `remora analyze <paths>` to the full pipeline: load config → discover nodes → run coordinator → display results.
- Wire `remora watch <paths>` to file watching loop with debounce.
- Wire `remora config [-f yaml|json]` to load and display merged configuration.
- Wire `remora list-agents [-f table|json]` to scan `agents_dir` and show subagent status.
- Set correct exit codes: `0` success, `1` partial failure (some ops failed), `2` total failure, `3` config error.
- Implement debounced watch mode using `watchfiles`.

## Suggested File Targets
- `remora/cli.py` (full implementation, replacing stubs from Step 1)
- `remora/watcher.py`

## analyze Command

```python
@app.command()
def analyze(
    paths: list[Path] = typer.Argument(..., help="Files or directories to analyze"),
    operations: str = typer.Option("lint,test,docstring", help="Comma-separated operation list"),
    format: str = typer.Option("table", help="Output format: table, json, interactive"),
    config: Optional[Path] = typer.Option(None, "--config", "-c"),
    auto_accept: bool = typer.Option(False, help="Auto-accept all results"),
) -> None:
    cfg = load_config(config)
    ops = [op.strip() for op in operations.split(",")]
    analyzer = RemoraAnalyzer(cfg, cairn_client=build_cairn_client(cfg))

    results = asyncio.run(analyzer.analyze(paths, operations=ops))

    presenter = ResultPresenter(format=format)
    presenter.display(results)

    if auto_accept:
        asyncio.run(analyzer.bulk_accept())
    elif format == "interactive":
        asyncio.run(presenter.interactive_review(analyzer, results))

    raise SystemExit(_exit_code(results))
```

## list-agents Command

```python
@app.command(name="list-agents")
def list_agents(
    format: str = typer.Option("table", help="Output format: table, json"),
    config: Optional[Path] = typer.Option(None),
) -> None:
    cfg = load_config(config)

    agents = []
    for op_name, op_config in cfg.operations.items():
        yaml_path = cfg.agents_dir / op_config.subagent
        gguf_path = ... # derive from YAML if it exists
        agents.append({
            "name": op_name,
            "yaml": str(yaml_path),
            "yaml_exists": yaml_path.exists(),
            "gguf": str(gguf_path) if gguf_path else "not configured",
            "gguf_exists": gguf_path.exists() if gguf_path else False,
        })

    if format == "json":
        typer.echo(json.dumps(agents, indent=2))
    else:
        # Rich table with status indicators
        ...
```

## Watch Mode

```python
# remora/watcher.py
import asyncio
from watchfiles import awatch

async def watch_and_analyze(
    paths: list[Path],
    analyzer: RemoraAnalyzer,
    debounce_ms: int = 500,
) -> None:
    pending: set[Path] = set()
    debounce_task: asyncio.Task | None = None

    async def trigger_analysis():
        files = list(pending)
        pending.clear()
        results = await analyzer.analyze(files)
        presenter = ResultPresenter(format="table")
        presenter.display(results)

    async for changes in awatch(*paths):
        for change_type, changed_path in changes:
            if changed_path.endswith(".py"):
                pending.add(Path(changed_path))

        if debounce_task:
            debounce_task.cancel()
        debounce_task = asyncio.create_task(
            _debounced(trigger_analysis, debounce_ms / 1000)
        )

async def _debounced(coro_fn, delay: float):
    await asyncio.sleep(delay)
    await coro_fn()
```

## Exit Code Mapping

| Condition | Exit Code |
|---|---|
| All operations successful | `0` |
| Some operations failed | `1` |
| All operations failed / no nodes found | `2` |
| Config error | `3` |
| Unexpected exception | `4` |

## list-agents Output (table format)

```
┌──────────────┬──────────────────────────────────────┬────────────┬────────────┐
│ Agent        │ YAML                                 │ YAML       │ GGUF       │
├──────────────┼──────────────────────────────────────┼────────────┼────────────┤
│ lint         │ agents/lint/lint_subagent.yaml        │ ✓ found    │ ✓ found    │
│ test         │ agents/test/test_subagent.yaml        │ ✓ found    │ ✗ missing  │
│ docstring    │ agents/docstring/docstring_subagent..│ ✓ found    │ ✗ missing  │
│ sample_data  │ agents/sample_data/sample_data_sub.. │ ✓ found    │ ✗ missing  │
└──────────────┴──────────────────────────────────────┴────────────┴────────────┘
```

## Implementation Notes
- `asyncio.run()` is used to run the async analysis from the synchronous Typer command handler. This is the standard pattern — no need for a custom event loop.
- The debounce in watch mode uses task cancellation: each new file change cancels the pending timer and restarts it. Only when no changes arrive for `debounce_ms` does the analysis run.
- Watch mode should print a startup message showing which paths are being watched and the debounce interval.
- `--auto-accept` on the CLI maps to `bulk_accept()` after analysis. Make clear in help text that this still requires YAML subagent definitions and GGUF models.

## Testing Overview
- **Integration test:** `remora analyze tests/fixtures/integration_target.py` completes and returns exit code 0 or 1.
- **Integration test:** `remora list-agents -f json` returns parseable JSON with all configured agents.
- **Unit test:** Watch mode debounce: two rapid file changes result in only one analysis run.
- **Unit test:** `--format json` produces valid JSON output.
- **Unit test:** Correct exit codes for all-success, partial-fail, and config-error cases.
