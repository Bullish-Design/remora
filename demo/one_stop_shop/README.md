# Remora One Stop Shop Demo

This demo shows Remora running against a realistic Python project with real vLLM calls and real Cairn workspaces. It exercises discovery, graph execution, Grail tools, workspaces, EventBus streaming, and the service/indexer entry points.

## What is included

- `project/`: a mini supply-chain planning library (Meridian) with multiple modules, data loaders, and a CLI.
- `remora.yaml`: demo configuration pointing at the Meridian project and the Remora agent bundles.
- `run_demo.py`: orchestrates a real app run + Remora graph execution + Cairn workspace inspection.

## Prerequisites

- A vLLM server running the Qwen model at `http://remora-server:8000/v1`.
- Remora dependencies installed (including structured-agents, grail, cairn, and vLLM bindings).

## Quick run (from repo root)

1. Start the vLLM server (example):

```bash
vllm serve Qwen/Qwen3-4B-Instruct-2507-FP8 \
  --enable-auto-tool-choice \
  --tool-call-parser qwen3_xml \
  --max-num-seqs 32 \
  --max-model-len 32768 \
  --enable-prefix-caching
```

2. Run the one-stop demo (runs the Meridian app, then Remora):

```bash
python demo/one_stop_shop/run_demo.py
```

Artifacts generated:
- `demo/one_stop_shop/outputs/meridian_plan.json`
- `demo/one_stop_shop/outputs/remora_events.jsonl`

3. Run the Remora CLI directly:

```bash
remora run demo/one_stop_shop/project/src --config demo/one_stop_shop/remora.yaml
```

4. Start the service server:

```bash
remora serve --config demo/one_stop_shop/remora.yaml
```

5. Start the indexer daemon:

```bash
remora-index demo/one_stop_shop/project/src
```

## Run the Meridian app only

```bash
python demo/one_stop_shop/project/src/meridian/cli.py \
  --data-dir demo/one_stop_shop/project/data \
  --output demo/one_stop_shop/outputs/meridian_plan.json
```

## Workspace layout

Remora uses Cairn to create a stable workspace plus per-agent workspaces:

- `demo/one_stop_shop/workspaces/one-stop-shop/stable.db`
- `demo/one_stop_shop/workspaces/one-stop-shop/<agent-id>.db`

The demo script reads one agent workspace and prints a file preview so you can confirm the Cairn-backed virtual filesystem is active.

## How this maps to Remora features

- Discovery: `remora.core.discovery.discover()` scans the Meridian codebase.
- Graph construction: `remora.core.graph.build_graph()` creates a dependency-aware plan.
- Execution: `remora.core.executor.GraphExecutor` runs agents with real vLLM calls.
- Grail tools: loaded from `agents/` and executed against a virtual FS.
- Workspaces: `CairnWorkspaceService` and `PathResolver` map project paths into Cairn.
- Event streaming: `EventBus` is used to log events to JSONL and to the console.
- Dashboard + indexer: CLI entry points consume the same event flow.

## Tips

- Run from the repo root so the bundle paths in `demo/one_stop_shop/remora.yaml` resolve correctly.
- To swap models or hosts, edit `demo/one_stop_shop/remora.yaml` or set the `REMORA_MODEL_*` env vars.
- Use `demo/one_stop_shop/outputs/remora_events.jsonl` to build a custom UI without touching the dashboard.
