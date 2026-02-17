# DEV GUIDE STEP 16: CLI + Watch Mode

## Goal
Deliver the complete end-to-end CLI experience: `analyze`, `watch`, `config`, and `list-agents` commands, all wired to the real analysis pipeline. Add reactive watch mode with debouncing.

## Why This Matters
The CLI is the only interface most users will interact with. It must wire every layer together (config → discovery → coordinator → runners → results → accept/reject) and handle the user's intent cleanly. `list-agents` is particularly important for transparency: users need to see which subagent definitions are loaded and whether the configured adapter is available on the vLLM server.

## Implementation Checklist
- Wire `remora analyze <paths>` to the full pipeline: load config → discover nodes → run coordinator → display results.
- Wire `remora watch <paths>` to file watching loop with debounce.
- Wire `remora config [-f yaml|json]` to load and display merged configuration.
- Wire `remora list-agents [-f table|json]` to scan `agents_dir`, show subagent YAML status, and check adapter availability via vLLM.
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

`list-agents` scans the configured `agents_dir` for subagent YAML files and checks whether the configured adapter is available on the vLLM server:

```python
@app.command(name="list-agents")
def list_agents(
    format: str = typer.Option("table", help="Output format: table, json"),
    config: Optional[Path] = typer.Option(None),
) -> None:
    cfg = load_config(config)
    available_models = _fetch_models(cfg.server)

    agents = []
    for op_name, op_config in cfg.operations.items():
        yaml_path = cfg.agents_dir / op_config.subagent
        adapter_name = op_config.model_id or cfg.server.default_adapter
        agents.append({
            "name": op_name,
            "yaml": str(yaml_path),
            "yaml_exists": yaml_path.exists(),
            "adapter": adapter_name,
            "model_available": adapter_name in available_models,
        })

    if format == "json":
        typer.echo(json.dumps(agents, indent=2))
    else:
        # Rich table with status indicators
        ...

def _fetch_models(server: ServerConfig) -> set[str]:
    """Return model IDs from the vLLM server; empty set on failure."""
    try:
        from openai import OpenAI
        client = OpenAI(
            base_url=server.base_url,
            api_key=server.api_key,
            timeout=server.timeout,
        )
        return {model.id for model in client.models.list().data}
    except Exception:
        return set()
```

## list-agents Output (table format)

```
┌──────────────┬──────────────────────────────────────┬────────────┬──────────────────────────────┬────────────┐
│ Agent        │ YAML                                 │ YAML       │ Adapter                      │ Available  │
├──────────────┼──────────────────────────────────────┼────────────┼──────────────────────────────┼────────────┤
│ lint         │ agents/lint/lint_subagent.yaml        │ ✓ found    │ lint                         │ ✓ ready    │
│ test         │ agents/test/test_subagent.yaml        │ ✓ found    │ test                         │ ✓ ready    │
│ docstring    │ agents/docstring/docstring_subagent.. │ ✓ found    │ docstring                    │ ✓ ready    │
│ sample_data  │ agents/sample_data/sample_data_sub.. │ ✗ missing  │ sample_data                  │ ✓ ready    │
└──────────────┴──────────────────────────────────────┴────────────┴──────────────────────────────┴────────────┘
```

Model availability is a single vLLM connectivity check — if the server is not reachable, all agents show "✗ unavailable".

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

## Implementation Notes
- `asyncio.run()` is used to run the async analysis from the synchronous Typer command handler. This is the standard pattern — no need for a custom event loop.
- The debounce in watch mode uses task cancellation: each new file change cancels the pending timer and restarts it. Only when no changes arrive for `debounce_ms` does the analysis run.
- Watch mode should print a startup message showing which paths are being watched and the debounce interval.
- `--auto-accept` on the CLI maps to `bulk_accept()` after analysis.

## Testing Overview
- **Integration test:** `remora analyze tests/fixtures/integration_target.py` completes and returns exit code 0 or 1.
- **Integration test:** `remora list-agents -f json` returns parseable JSON with all configured agents.
- **Unit test:** Watch mode debounce: two rapid file changes result in only one analysis run.
- **Unit test:** `--format json` produces valid JSON output.
- **Unit test:** Correct exit codes for all-success, partial-fail, and config-error cases.
- **Unit test:** `_fetch_models()` returns empty set when vLLM is not reachable.

