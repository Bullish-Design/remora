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
| `CONFIG_001` | Missing/unreadable configuration | Bad path or permissions | Fix path, run `remora config` |
| `CONFIG_003` | Config file could not be loaded | Invalid YAML | Validate YAML syntax |
| `CONFIG_004` | Agents directory not found | `agents_dir` wrong | Fix path or run from repo root |
| `DISC_001` | Query pack not found | Missing `.scm` files | Verify `src/remora/queries` or set `query_dir` |
| `DISC_004` | Source file parse error | Syntax error | Fix file or exclude it |
| `AGENT_001` | Bundle/tool validation error | Missing `bundle.yaml` or tool script | Check bundle layout |
| `AGENT_002` | Model server connection error | vLLM unreachable | Verify server and base URL |
| `AGENT_004` | Turn limit exceeded | Agent never terminated | Increase `runner.max_turns` or adjust prompts |

## Common Scenarios

### Bundle Not Found

Symptoms:
- Warnings about missing bundles.
- `AGENT_001` during initialization.

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
