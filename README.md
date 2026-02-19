# Remora

Local code analysis and enhancement using FunctionGemma subagents.

## Documentation

- `docs/CONFIGURATION.md`
- `docs/TROUBLESHOOTING.md`
- `docs/API_REFERENCE.md`

## vLLM setup

Remora uses a vLLM server on your Tailscale network. Follow the server bring-up guide, then point `remora.yaml` at the server.

```bash
uv run server/test_connection.py
```

Once the server is reachable, set `server.base_url` in your config and run `remora analyze <path>`.

## Demo dashboard

Run the Rich TUI to monitor agent activity and throughput. It toggles the event stream on start and restores the previous state on exit.

```bash
remora-tui
```

To generate demo traffic in another pane:

```bash
remora-demo
```

The demo enables `lint`, `docstring`, and a placeholder `type_check` operation (currently mapped to the lint subagent).

By default the dashboard uses `~/.cache/remora/events.jsonl` and `~/.cache/remora/events.control` (XDG cache override respected). Payload logging is enabled by default and truncated to a few thousand characters.

You can still run Remora with explicit streaming settings:

```bash
REMORA_EVENT_STREAM=1 REMORA_EVENT_STREAM_FILE=remora-events.jsonl remora ...
remora-tui --input remora-events.jsonl
```

CLI overrides (when wired into runtime) should take precedence over the env vars: `--event-stream/--no-event-stream` and `--event-stream-file`.
