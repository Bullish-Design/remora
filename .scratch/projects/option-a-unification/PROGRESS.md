# Option A: LSP→EventStore Unification — Progress

**Status: COMPLETE**

## Phase 1 — Core AgentNode Infrastructure (11 tasks)

| Task | Commit | What |
|------|--------|------|
| 1 | `bf8af8b` | AgentNode Pydantic model + ToolSchema dataclass |
| 2 | `07d7c11` | to_row()/from_row() serialization |
| 3 | `c5d8a86` | to_system_prompt(), to_code_lens(), to_hover(), to_code_actions(), to_document_symbol() |
| 4 | `f07399a` | AgentExtension base class + load_extensions() |
| 5 | `4922202` | NodeDiscoveredEvent / NodeRemovedEvent |
| 6 | `0735909` | nodes table schema (20 columns, 3 indexes) |
| 7 | `17f81a4` | NodeProjection class |
| 8 | `34dbec9` | Wired NodeProjection into EventStore.append() |
| 9 | `61c1989` | get_node() / list_nodes() query methods on EventStore |
| 10 | `11fefd1` | Exported types from core/__init__.py |
| 11 | `b9347df` | Full pipeline integration test |

## Phase 2 — LSP Migration (16 tasks)

| Task | Commit | What |
|------|--------|------|
| 1-3 | `2ed580e` | get_node_at_position(), set_node_status(), remove_nodes_for_file() on EventStore + 7 tests |
| 4 | `8a9b34c` | Watcher returns list[dict] instead of list[ASTAgentNode]. Adds full_name, parent_id. 7 tests. |
| 5+6 | `1b31b82` | documents.py emits events to EventStore. lens/hover/actions read from EventStore via AgentNode. |
| 7 | `ccaafd5` | commands.py uses EventStore query methods |
| 8 | `6b6bd1b` | runner.py uses EventStore+AgentNode. All ASTAgentNode refs removed. 11 tests. |
| 9 | `a97a687` | notifications.py uses EventStore. 3 tests. |
| 10 | `5fcd2a8` | server.py imports AgentNode+ToolSchema from core. 3 tests. |
| 11+12 | `6fb771e` | Deleted ASTAgentNode and ToolSchema from lsp/models.py. Deleted lsp/extensions.py. |
| 13+14 | `5b3061d` | Removed RemoraDB nodes table. LazyGraph reads nodes from EventStore, edges from RemoraDB. |
| 15 | (covered) | Integration test — existing test covers full pipeline |
| 16 | `7f90eaf` | Final cleanup — removed all remora_id references from LSP subsystem |

## Final State

- 205 tests passing (1 pre-existing failure: missing workspace/executeCommand capability)
- Zero `remora_id` references remaining in `src/remora/`
- Single source of truth: EventStore `nodes` table for all node state
- RemoraDB retains: edges, proposals, cursor_focus, command_queue, events, activation_chain
