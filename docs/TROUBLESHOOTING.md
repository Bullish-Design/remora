# Troubleshooting

This guide covers common failures, error codes, and where to look for diagnostics.

## Quick Checks

1. Verify configuration:
   - Run `remora config` to inspect resolved values.
   - Confirm `agents_dir` points to the bundle directory.
2. Check inference server reachability:
   - Validate `server.base_url` and network connectivity.
3. Enable logs for more context:
   - Set `event_stream.enabled: true` for JSONL events.
   - Set `llm_log.enabled: true` for readable transcripts.

## Error Codes

Remora uses structured error codes from `remora.errors`.

| Code | Meaning | Typical Causes | Suggested Fix |
| --- | --- | --- | --- |
| `REMORA-CONFIG` | Configuration error | Missing config, invalid YAML, bad `agents_dir` | Fix config path or values |
| `REMORA-DISCOVERY` | Discovery error | Missing query packs, unreadable files, parse issues | Verify queries or exclude bad files |
| `REMORA-AGENT` | Bundle/tool error | Missing `bundle.yaml` or tool script | Check bundle layout |
| `REMORA-EXEC` | Execution error | Agent run failure or tool crash | Inspect logs, retry or adjust tools |

## Common Scenarios

### Bundle Not Found

Symptoms:
- Warnings about missing bundles.
- `REMORA-AGENT` during initialization.

Fixes:
- Ensure `operations.*.subagent` points to a directory with `bundle.yaml`.
- Confirm tool scripts exist in `agents/<op>/tools`.

### No Nodes Discovered

Symptoms:
- Empty results or `No operations run` output.

Fixes:
- Verify the paths passed to `remora analyze`.
- Confirm the query pack is available and matches the language.

### Event Stream Empty

Symptoms:
- `remora-tui` shows no events.

Fixes:
- Ensure `event_stream.enabled` is true.
- Verify the output path is writable.

## Logging and Diagnostics

- Event stream output: `event_stream.output`.
- Control file: `event_stream.control_file` (used by `remora-tui`).
- LLM transcripts: `llm_log.output`.
