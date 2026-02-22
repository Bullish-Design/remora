# Remora Architecture

## System Overview

Remora is a local orchestration layer that runs structured, tool-calling agents on Python code. The pipeline is:

1. **Discovery** — tree-sitter extracts CST nodes from Python files.
2. **Orchestration** — a coordinator fans out each node to enabled operations.
3. **Kernel Execution** — `KernelRunner` drives a structured-agents kernel and Grail tool execution.
4. **Results + Review** — results are aggregated and (optionally) merged from Cairn workspaces.

Inference is performed by an OpenAI-compatible server (typically vLLM) using FunctionGemma adapters.

## Architecture Layers

```
┌───────────────────────────────────────────────────────────┐
│ Application Layer                                         │
│  - CLI (remora)                                           │
│  - Config (Pydantic)                                      │
│  - Watch mode (watchfiles)                                │
│  - Hub daemon (optional)                                  │
└───────────────────────────────────────────────────────────┘
                        ↓
┌───────────────────────────────────────────────────────────┐
│ Discovery Layer                                           │
│  - Tree-sitter parser + queries                           │
│  - CSTNode extraction                                     │
└───────────────────────────────────────────────────────────┘
                        ↓
┌───────────────────────────────────────────────────────────┐
│ Orchestration Layer                                       │
│  - Coordinator + concurrency control                      │
│  - Result aggregation                                     │
└───────────────────────────────────────────────────────────┘
                        ↓
┌───────────────────────────────────────────────────────────┐
│ Kernel Execution Layer                                    │
│  - Structured-agents AgentKernel                          │
│  - Grail backend for .pym tools                            │
│  - ContextManager + Decision Packet                       │
└───────────────────────────────────────────────────────────┘
                        ↓
┌───────────────────────────────────────────────────────────┐
│ Workspace Layer                                           │
│  - Cairn workspaces per agent run                          │
│  - CairnWorkspaceBridge handles manual or auto-merge       │
└───────────────────────────────────────────────────────────┘
```

## Core Components

### CLI (`remora.cli`)

Commands include `analyze`, `watch`, `config`, and `list-agents`. The CLI resolves config overrides and drives the analysis workflow.

### Discovery (`remora.discovery`)

`TreeSitterDiscoverer` loads `.scm` query packs from `src/remora/queries`, parses Python files concurrently via `ThreadPoolExecutor`, and returns immutable `CSTNode` objects.

### Coordinator (`remora.orchestrator.Coordinator`)

The coordinator enforces concurrency limits, builds `KernelRunner` instances, and aggregates `NodeResult` outputs. The Coordinator can also spawn the Hub as an `in-process` task. Each operation produces a unique `agent_id` used as the workspace identifier.

### KernelRunner (`remora.kernel_runner.KernelRunner`)

`KernelRunner` loads a bundle (`agents/<op>/bundle.yaml`), configures a structured-agents kernel, and runs a multi-turn tool-calling loop. It also:

- Builds initial messages using bundle templates.
- Injects per-turn context from the Decision Packet.
- Executes Grail tools in Cairn workspaces.
- Formats the final `AgentResult` using the termination tool output.

### Context Manager (`remora.context`)

The Decision Packet summarizes recent tool activity and errors for prompt injection. It can pull additional context from the optional Hub daemon (`remora-hub`), which can run either as a separate process or as an in-process asyncio task inside the `Coordinator`.

### Events and Logs (`remora.events`, `remora.llm_logger`)

Event emitters produce JSONL event streams for dashboards and debugging. When enabled, `LlmConversationLogger` writes human-readable transcripts.

## Bundle Layout

Each operation lives under `agents/<operation>` and contains:

- `bundle.yaml` — structured-agents bundle manifest.
- `tools/` — Grail `.pym` tool scripts.
- `context/` — optional context providers.

## Workspace Management

Grail tools run inside Cairn workspaces stored under `~/.cache/remora/workspaces/<agent_id>` (or `cairn.home`). Successful runs can be merged into the project root via `RemoraAnalyzer.accept()` or `--auto-accept`, which delegates to the `CairnWorkspaceBridge`.

## Data Flow

```
remora analyze src/
  → load config
  → discover CST nodes
  → for each node + operation:
      - load bundle
      - run structured-agents kernel
      - execute tools in workspace
      - emit events + logs
  → aggregate results (table/json)
  → optional accept/reject
```
