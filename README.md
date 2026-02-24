# Remora

Local code analysis and enhancement using easily swappable agent bundles, tree-sitter discovery, and Grail tool execution.

Remora scans Python projects into CST nodes, runs specialized agent bundles (lint, test, docstring, sample_data) against each node, and lets you review or auto-merge changes produced inside isolated Cairn workspaces. Inference is performed via an OpenAI-compatible server (typically vLLM).

## Quick Start

1. Start a vLLM server reachable at `server.base_url` (default: `http://remora-server:8000/v1`).
2. Copy `remora.yaml.example` to `remora.yaml` and adjust `server` + `agents_dir`.
3. Run an analysis:

```bash
remora analyze src/
```

To auto-accept successful changes:

```bash
remora analyze src/ --auto-accept
```

## CLI Overview

- `remora analyze [PATHS...]` — run analysis and report results.
- `remora watch [PATHS...]` — watch for changes and re-run analysis.
- `remora list-agents` — verify bundle availability and model adapters.
- `remora config` — print the merged configuration.
- `remora-hub start|status|stop` — manage the optional Hub daemon.
- `remora-tui` — live dashboard for the JSONL event stream.
- `remora-demo` — generate demo traffic for the dashboard.
- `remora-flood` — stress-test the vLLM endpoint.

## Agent Bundles

Each operation is a structured-agents bundle stored under `agents/<operation>/`:

```
agents/lint/
├── bundle.yaml
├── tools/            # Grail .pym tools
└── context/          # Optional context providers
```

`bundle.yaml` declares the model adapter, tool catalog, termination tool, and prompt templates. Tools run through Grail and Cairn inside per-agent workspaces.

## Event Streaming & Logs

Enable event streaming to capture agent progress as JSONL:

```yaml
event_stream:
  enabled: true
```

Then run:

```bash
remora-tui
```

Human-readable transcripts are available via `llm_log.enabled`.

## Documentation

- `docs/CONCEPT.md` — conceptual overview
- `docs/ARCHITECTURE.md` — architecture and data flow
- `docs/CONFIGURATION.md` — `remora.yaml` reference
- `docs/API_REFERENCE.md` — CLI + Python APIs
- `docs/SPEC.md` — technical spec
- `docs/TROUBLESHOOTING.md` — diagnostics
