# Troubleshooting

This guide covers common failures, error codes, and where to look for diagnostics.

## Quick Checks

1. Verify your configuration:
   - `remora config` to print the merged config.
   - Ensure `agents_dir` points to the correct `agents/` directory.
2. Confirm server reachability:
   - Check `server.base_url` in `remora.yaml`.
   - Ensure the vLLM server is reachable on your network.
3. Enable event logging for more context:
   - Set `event_stream.enabled: true` or `REMORA_EVENT_STREAM=true`.
   - Output defaults to `~/.cache/remora/events.jsonl` (XDG cache respected).

## Error Codes

Remora uses structured error codes to make failures easier to diagnose.

| Code | Meaning | Typical Causes | Suggested Fix |
| --- | --- | --- | --- |
| `CONFIG_003` | Configuration file could not be loaded | Missing file or invalid YAML | Check path, validate YAML, run `remora config` |
| `CONFIG_004` | Agents directory could not be found | `agents_dir` path is wrong | Update `agents_dir` or run from project root |
| `DISC_001` | Discovery query pack not found | `query_pack` missing | Ensure `src/remora/queries` exists or set `query_dir` |
| `DISC_004` | Source file parse failure | Invalid syntax or unreadable file | Fix syntax, rerun analysis |
| `AGENT_001` | Subagent or tool registry error | Missing `.pym` or invalid tool schema | Check subagent YAML and tool scripts |
| `AGENT_002` | Model server connection error | vLLM unreachable or timeout | Confirm server is running and reachable |
| `AGENT_003` | Runner validation failure | Malformed `submit_result` payload | Check tool outputs and subagent definitions |
| `AGENT_004` | Turn limit exceeded | Model loop never submitted result | Increase `runner.max_turns` or adjust prompts |

## Common Scenarios

### Server Connection Failures

Symptoms:
- Agent errors with `AGENT_002`.
- Event stream shows `model_response` with `status=error`.

Fixes:
- Check `server.base_url` and network connectivity.
- Increase `server.timeout` if responses are slow.

### Missing Subagent Definitions

Symptoms:
- Warning: `Subagent definition missing`.
- `AGENT_001` errors during initialization.

Fixes:
- Confirm `agents_dir` and `operations.*.subagent` paths.
- Ensure subagent YAML files exist and are valid YAML.

### Tool Execution Errors

Symptoms:
- Tool results with `error` fields.
- `AGENT_003` on validation failure.

Fixes:
- Check the tool script for invalid JSON or missing fields.
- Make sure the tool returns a valid `submit_result` payload when required.

### Discovery Returns No Nodes

Symptoms:
- Empty results or `No operations run` output.

Fixes:
- Verify the `paths` you pass to `remora analyze`.
- Confirm `discovery.language` and `query_pack` match available queries.

## Logging and Diagnostics

- Event stream: `event_stream.enabled`, output in `event_stream.output`.
- LLM logs: `llm_log.enabled`, output in `llm_log.output`.
- Control file: `event_stream.control_file` can toggle logging at runtime.

Environment overrides:
- `REMORA_EVENT_STREAM=true|false`
- `REMORA_EVENT_STREAM_FILE=/path/to/events.jsonl`
