# Phase 2 Code Review — Test Findings

All test files reviewed (excluding `test_graph_*` and `test_web_layout.py` which test `remora_demo/`).

---

## Test Suite Structure

### Directory Layout
```
tests/
├── conftest.py              — Shared fixtures (177 lines)
├── helpers.py               — DEPRECATED shim → remora.testing
├── test_discovery.py        — compute_node_id, CSTNode, discover()
├── test_main.py             — __main__ invokes CLI
├── test_tool_script_fuzzing.py — Hypothesis fuzz test
├── unit/
│   ├── test_agent_node.py   — AgentNode creation, serialization, LSP output
│   ├── test_node_events.py  — NodeDiscoveredEvent, NodeRemovedEvent
│   ├── test_projections.py  — Insert, upsert, extension matching, status
│   ├── test_event_store.py  — Basic CRUD (append, replay, count, graph_ids, delete)
│   ├── test_event_store_projection.py — Append triggers projection
│   ├── test_event_store_nodes_query.py — get_node, list_nodes, get_node_at_position
│   ├── test_event_bus.py    — Emit, stream, wait_for
│   ├── test_subscriptions.py — Register, defaults, matching, pattern matching
│   ├── test_swarm_state.py  — Upsert, list, mark_orphaned, update
│   ├── test_extensions.py   — Load from dir, mtime caching, alphabetical order
│   ├── test_lsp_watcher.py  — Parse functions/classes/methods, preserve IDs
│   ├── test_lsp_runner.py   — EventStore-based dispatch, execute_turn, proposals, tools
│   ├── test_lsp_graph.py    — LazyGraph reads from EventStore, invalidate
│   ├── test_lsp_db.py       — RemoraDB events, proposals, cursor_focus, no-nodes-table
│   ├── test_lsp_models.py   — ToolSchema, RewriteProposal, code actions, events
│   ├── test_lsp_server.py   — No ASTAgentNode import, uses core ToolSchema
│   ├── test_lsp_notifications.py — cursor_moved reads EventStore not DB
│   ├── test_command_polling.py — Push/poll/mark_done roundtrip
│   └── test_command_queue.py — Table exists, push/poll, mark_done, ordering
├── integration/
│   ├── helpers.py           — vLLM config, workspace state helpers (271 lines)
│   ├── test_lsp_integration.py — Full LSP lifecycle, handlers, CLI smoke
│   ├── test_agent_node_pipeline.py — EventLog→nodes→AgentNode full lifecycle
│   ├── test_agent_runner.py — Cascade depth limits, cooldown, concurrency
│   ├── test_event_store_integration.py — Concurrent append, trigger delivery pipeline
│   ├── test_swarm_store.py  — SwarmState persistence, subscription pattern matching
│   ├── test_reconcile_real.py — Reconciler creates agents, content-changed events
│   ├── test_vllm_real.py    — Real LLM tests (tool calling, grail tools, multi-agent)
│   ├── test_cli_real.py     — CLI serve smoke, invalid config
│   ├── test_multilanguage_discovery_real.py — Python/TOML/Markdown discovery
│   └── test_real_code_discovery_real.py — Real-world project, large files, edge cases
├── fixtures/
│   └── mock_llm.py          — MockLLMClient (10 lines, minimal)
├── utils/
│   ├── grail_runtime.py     — Grail test harness helpers
│   └── test_fs.py           — managed_workspace tests
├── roundtrip/
│   └── run_harness.py       — Manual round-trip test for discovery pipeline
└── snapshots/               — (empty/not examined)
```

### Testing Module in Source
```
src/remora/testing/
├── __init__.py  — Re-exports fakes
└── fakes.py     — FakeAsyncOpenAI, FakeChatCompletions, FakeGrailExecutor (120 lines)
```

---

## Findings by Severity

### HIGH — Coverage Gaps

#### H1. No Tests for core/agent_runner.py Core Runner Loop
`test_agent_runner.py` tests cascade prevention (depth limits, cooldowns, concurrency) but does NOT test the actual `run_forever()` event processing loop, the `_dispatch_trigger` logic, or integration with `SwarmExecutor`. The mock replaces `_executor` entirely, so we never verify that the runner correctly loads AgentState, invokes the executor, and handles results.

#### H2. No Tests for core/swarm_executor.py
The `SwarmExecutor` (375 lines) — which handles LLM communication, tool dispatch, grail execution, and agent turns — has ZERO direct tests. It is only tested indirectly through `test_agent_runner.py` where it's mocked out.

#### H3. No Tests for core/chat.py
The `ChatSession` class (259 lines) — which manages conversation history, LLM interaction, and tool calling — has no tests at all.

#### H4. No Tests for service/ Package
`service/api.py` (200 lines), `service/handlers.py` (147 lines), `service/datastar.py` (68 lines), `service/chat_service.py` (243 lines) — none have tests. This includes the duplicate `get_subscriptions` bug in `api.py` which is untested.

#### H5. No Tests for cli/main.py
The CLI (338 lines) has no unit tests. Only `test_cli_real.py` does subprocess-level integration tests for `serve` and invalid config, but `swarm start`, `swarm reconcile`, `swarm list`, and `swarm stop` are untested.

#### H6. No Tests for nvim/server.py
The Neovim integration (265 lines) has no tests.

#### H7. No Tests for ui/ Package
`ui/projector.py` (197 lines), `ui/view.py` (144 lines), and all `ui/components/` — no tests.

#### H8. No Tests for adapters/starlette.py
The Starlette adapter (138 lines) has no tests.

### MEDIUM — Quality Issues

#### M1. test_lsp_db.py Tests Absence Rather Than Behavior
Several tests in `test_lsp_db.py` verify that methods/tables DON'T exist (lines 121-138), which is a migration guard but fragile. These should be in a separate "migration guard" file to clearly separate concerns.

#### M2. Duplicate _make_node Helper
`_make_node()` is duplicated across: `test_lsp_models.py`, `test_lsp_server.py`, `test_lsp_notifications.py`. Should be extracted to a shared fixture or the `remora.testing` module.

#### M3. test_agent_runner.py Uses AgentState (Pre-Unification)
The integration test creates `AgentState` JSONL files via `_ensure_agent_state()`. This tests the pre-unification code path rather than the EventStore-based path. Once AgentState is eliminated, these tests will need rewriting.

#### M4. Hardcoded vLLM Config in Tests
`test_vllm_real.py` and `integration/helpers.py` hardcode `http://remora-server:8000/v1` and `Qwen/Qwen3-4B-Instruct-2507-FP8`. The helpers do support env var overrides, but the pattern is scattered.

#### M5. MockLLMClient is Trivially Simple
`tests/fixtures/mock_llm.py` (10 lines) returns empty tool_calls and no content. It can't test any actual LLM interaction logic. The `remora.testing.fakes` module is much richer but `MockLLMClient` is never used alongside it.

#### M6. tests/helpers.py Deprecated but Not Removed
The file emits a deprecation warning and re-exports from `remora.testing`, but it still exists.

#### M7. roundtrip/run_harness.py Uses NodeType Enum
Line 29 imports `NodeType` from `discovery.py`, which was flagged as dead/stale code in source findings. This is the only consumer.

#### M8. Pre-Existing Test Failure
`test_lsp_handlers_register_and_advertise_capabilities` fails (205 passed, 1 failed). This has been pre-existing and should be fixed.

### LOW — Minor Issues

#### L1. No Snapshot Tests
The `tests/snapshots/` directory exists but appears empty. Snapshot testing for LSP output (code lens, hover, code actions) could catch regressions.

#### L2. test_swarm_store.py Overlaps with test_subscriptions.py
`test_swarm_store.py` tests subscription pattern matching extensively, duplicating coverage already in `test_subscriptions.py`. The SwarmState tests themselves are also redundant with `test_swarm_state.py`.

#### L3. conftest.py Fixtures Include DummyKernel
`DummyKernel` and `DummyResult` are defined in conftest but it's unclear if any current test uses them.

---

## Coverage Summary by Component

| Component | Unit Tests | Integration Tests | Coverage Assessment |
|-----------|-----------|-------------------|---------------------|
| AgentNode | Thorough | Thorough | Good |
| Events (core) | Good | Good | Good |
| Projections | Good | Good | Good |
| EventStore | Good | Thorough | Good |
| EventBus | Good | - | Adequate |
| Subscriptions | Good | Good | Good |
| AgentRunner | Partial (guards only) | Partial | **Gap: no run loop test** |
| SwarmExecutor | None | None | **Critical gap** |
| ChatSession | None | None | **Critical gap** |
| SwarmState | Good | Good | Good (but may be dead code) |
| Discovery | Good | Thorough | Good |
| Extensions | Good | Good | Good |
| LSP Watcher | Good | - | Good |
| LSP Runner | Thorough | - | Good |
| LSP Graph | Good | - | Good |
| LSP DB | Good | - | Good |
| LSP Models | Good | - | Good |
| LSP Server | Basic | Good | Adequate |
| LSP Notifications | Good | - | Good |
| Command Queue | Good | - | Good |
| Reconciler | - | Good | Adequate |
| Service API | None | None | **Critical gap** |
| CLI | None | Basic subprocess | **Gap** |
| Nvim | None | None | **Gap** |
| UI | None | None | **Gap** |
| Adapters | None | None | **Gap** |
| Testing fakes | (used by other tests) | - | N/A |

---

## Key Observations

1. **Core event pipeline is well-tested** — EventStore, projections, subscriptions, AgentNode all have solid coverage.
2. **LSP subsystem is well-tested** — Post-unification migration tests verify EventStore integration throughout.
3. **Agent execution is the biggest gap** — SwarmExecutor and ChatSession have zero tests. AgentRunner only tests guards.
4. **Peripheral packages untested** — service/, ui/, nvim/, adapters/ have no tests.
5. **Pre-unification code still tested** — Tests for SwarmState and AgentState JSONL persist, testing code that should eventually be removed.
6. **Test organization is clean** — Clear unit/integration separation, well-named files.
7. **Real integration tests require external infrastructure** — vLLM server, which is appropriate for a `pytest.mark.integration` setup.
