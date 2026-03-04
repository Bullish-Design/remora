# Codebase Cross-Reference Analysis

Verified documentation claims against actual source code in `src/remora/`.

---

## Classes & Types Referenced in Docs

### REMOVED (docs referencing these are STALE)

| Class/Type | Referenced In | Status |
|---|---|---|
| `SwarmState` | README.md, HOW_TO_USE_REMORA.md, docs/ARCHITECTURE.md, docs/CONCEPT.md | **DOES NOT EXIST** — removed during EventBased unification |
| `AgentState` | docs/CONCEPT.md, docs/ARCHITECTURE.md | **DOES NOT EXIST** — unified into AgentNode |
| `ASTAgentNode` | NEOVIM_DEMO_V21_FINAL_CONCEPT.md | **DOES NOT EXIST** — unified into AgentNode |
| `ExtensionNode` | NEOVIM_DEMO_V21_FINAL_CONCEPT.md | **DOES NOT EXIST** — unified into AgentNode |
| `AgentRunner` | docs/ARCHITECTURE.md (uppercase) | **DOES NOT EXIST** — replaced by SwarmExecutor |
| `KernelRunner` | docs/CONCEPT.md | **DOES NOT EXIST** — old V1 concept |
| `Hub Context` | docs/CONCEPT.md | **DOES NOT EXIST** — old V1 concept |
| `Decision Packet` | docs/CONCEPT.md | **DOES NOT EXIST** — old V1 concept |
| `AgentMetadata` | HOW_TO_USE_REMORA.md | **VERIFY** — may still exist as part of config/models |

### EXISTS (correctly referenced)

| Class/Type | Location | Referenced By |
|---|---|---|
| `AgentNode` | `src/remora/core/agent_node.py:67` | docs/EventBased_Concept.md, docs/architecture.md |
| `EventStore` | `src/remora/core/event_store.py` | docs/EventBased_Concept.md, docs/architecture.md, HOW_TO_USE_REMORA.md |
| `SubscriptionRegistry` | `src/remora/core/subscriptions.py` | docs/EventBased_Concept.md, docs/architecture.md, HOW_TO_USE_REMORA.md |
| `RemoraConfig` | `src/remora/core/config.py` | docs/CONFIGURATION.md |
| `SwarmExecutor` | `src/remora/core/swarm_executor.py` | docs/architecture.md |
| `RemoraService` | `src/remora/service/api.py` | docs/REMORA_UI_API.md (partially stale) |

---

## CLI Commands

### Verified in `src/remora/cli/main.py`

| Command | Status | Notes |
|---|---|---|
| `remora swarm start` | EXISTS | Core swarm launch command |
| `remora swarm reconcile` | EXISTS | Trigger reconciliation |
| `remora swarm list` | EXISTS | List agents |
| `remora swarm emit` | EXISTS | Emit events |
| `remora serve` | EXISTS | Start HTTP service |
| `remora run` | **DOES NOT EXIST** | Referenced in docs/SPEC.md — stale |

---

## Service API Endpoints

### Verified in `src/remora/service/api.py` (RemoraService class)

| Method | Status | Notes |
|---|---|---|
| `subscribe_stream` | EXISTS | SSE subscription endpoint |
| `events_stream` | EXISTS | SSE event stream |
| `input` | EXISTS | User input endpoint |
| `config_snapshot` | EXISTS | Config snapshot |
| `get_agent` | EXISTS | Get agent by ID |
| `get_agent_subscriptions` | EXISTS | Get subscriptions for agent |
| `/run` | **DOES NOT EXIST** | Referenced in REMORA_UI_API.md — stale |
| `/plan` | **DOES NOT EXIST** | Referenced in REMORA_UI_API.md — stale |
| `/snapshot` | **DOES NOT EXIST** | Referenced in REMORA_UI_API.md — stale |

---

## Installation & Package

| Claim | Status | Notes |
|---|---|---|
| `pip install remora` | **FALSE** | Not published to PyPI. Multiple docs reference this incorrectly: README.md, INSTALLATION.md, getting-started.md |
| `remora.yaml.example` | EXISTS | At repo root, correctly referenced in README.md |
| Python 3.14 support | **UNVERIFIED** | Referenced in INSTALLATION.md — check pyproject.toml |
| Extras: backend, frontend, full | **UNVERIFIED** | Referenced in INSTALLATION.md — check pyproject.toml |

---

## Tool System

### Verified in `src/remora/core/tools/`

| Tool Module | Status |
|---|---|
| `grail.py` | EXISTS — Grail sandboxed script integration |
| `lsp.py` | EXISTS — LSP tool integration |
| `spawn_child.py` | EXISTS — Child agent spawning |
| `swarm.py` | EXISTS — Swarm-level tools |

---

## Key Source Structure (verified)

```
src/remora/
├── core/          — agent_node, events, event_store, subscriptions, projections,
│                    config, discovery, reconciler, swarm_executor, chat,
│                    kernel_factory, manifest, execution, cairn_bridge, workspace,
│                    tools/ (grail, lsp, swarm, spawn_child)
├── lsp/           — server, runner, watcher, db, graph, models,
│                    handlers/, nvim/, notifications
├── cli/           — main, workspace
├── service/       — api, chat_service, handlers, datastar
├── adapters/      — starlette
├── ui/            — components/, projector, view
├── models/        — __init__
├── workspace/     — sandbox, sync, validation, inspector
├── testing/       — mock_workspace
├── utils/         — fs, path_resolver, text, types
├── extensions.py
├── fixtures/
└── queries/       — tree-sitter .scm files
```

---

## Impact Summary

### Docs with STALE references that need updating:
1. **README.md** — SwarmState reference, pip install
2. **HOW_TO_USE_REMORA.md** — SwarmState import, AgentMetadata import
3. **docs/ARCHITECTURE.md** (uppercase) — SwarmState, AgentRunner, AgentState
4. **docs/CONCEPT.md** — Entire document is V1 architecture (DELETE)
5. **docs/SPEC.md** — `remora run` command, old bundle format
6. **docs/REMORA_UI_API.md** — /run, /plan, /snapshot endpoints
7. **docs/INSTALLATION.md** — pip install, unverified extras
8. **docs/guides/getting-started.md** — pip install
9. **docs/TROUBLESHOOTING.md** — `agents_dir`, `operations.*.subagent` field names
10. **docs/TESTING_GUIDELINES.md** — old test structure, no mention of Hypothesis tests
