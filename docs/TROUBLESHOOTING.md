# Troubleshooting

Common failures, error types, and where to look for diagnostics.

## Quick Checks

1. **Verify configuration**: Check `remora.yaml` values. Key fields: `bundle_root`, `discovery_paths`, `model_base_url`.
2. **Check inference server**: Validate `model_base_url` and network connectivity to the vLLM server.
3. **Check agent discovery**: Run `remora swarm list` to confirm agents are being discovered from your source paths.

## Error Types

Remora uses structured errors from `remora.core.errors`:

| Error Class | Meaning | Typical Causes | Suggested Fix |
|---|---|---|---|
| `ConfigError` | Configuration error | Missing config, invalid YAML, bad field values | Check `remora.yaml` structure and paths |
| `DiscoveryError` | Discovery error | Missing tree-sitter queries, unreadable files | Verify `discovery_paths` and file permissions |
| `ExecutionError` | Execution error | Agent run failure, tool crash, timeout | Inspect logs, check `max_turns` / `timeout_s` |
| `WorkspaceError` | Workspace error | Cairn/AgentFS failure, permission issues | Check `.remora/` directory and Cairn availability |

## Common Scenarios

### Bundle Not Found

Symptoms:
- Warnings about missing bundles during swarm start.
- `ExecutionError` during agent initialization.

Fixes:
- Ensure `bundle_root` in `remora.yaml` points to the directory containing your bundles.
- Confirm `bundle_mapping` maps node types to valid bundle YAML files.
- Check that bundle directories contain `bundle.yaml` and the referenced tool scripts.

### No Nodes Discovered

Symptoms:
- `remora swarm list` shows no agents.
- Empty results from `remora swarm start`.

Fixes:
- Verify `discovery_paths` in `remora.yaml` points to directories with source code.
- Check `discovery_languages` matches your codebase (e.g., `["python"]`).
- Ensure tree-sitter parsers are installed for the target languages.

### Events Not Flowing

Symptoms:
- Service endpoints return empty event streams.
- Agents not triggering on emitted events.

Fixes:
- Check that the EventStore is initialized: `.remora/events/events.db` should exist after `remora swarm start`.
- Verify agent subscriptions match the emitted event types.
- Check `remora swarm emit` with a known event type to test the pipeline.

### Workspace Errors

Symptoms:
- `WorkspaceError` during agent execution.
- Missing or inaccessible agent workspace directories.

Fixes:
- Verify `.remora/` directory is writable.
- Check that Cairn (AgentFS via fsdantic) is available: `python -c "import fsdantic"`.
- Check `.remora/stable.db` exists (created during reconciliation).

## Logging and Diagnostics

- **EventStore**: Events are persisted to `.remora/events/events.db` (SQLite). Use `remora swarm emit` to test event flow.
- **Service endpoints**: `GET /events` provides a live SSE stream for debugging. `GET /snapshot` shows current UI state.
- **Python logging**: Standard `logging` module is used throughout. Set log level via environment or config to see detailed output.
