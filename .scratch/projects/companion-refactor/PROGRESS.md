# Companion Refactor — Progress

> **CRITICAL RULES:**
> - **NO SUBAGENTS** — Do ALL work directly.
> - **NEVER STOP AFTER COMPACTION** — Resume immediately.

---

## Pre-Work

| # | Task | Status |
|---|------|--------|
| 0.1 | Create project workspace + concept doc | done |
| 0.2 | Write COMPANION_REFACTOR_GUIDE.md | done |

## Phase 0: Deletion

| # | Task | Status |
|---|------|--------|
| 0.1 | Delete companion/handlers/ directory | pending |
| 0.2 | Delete companion/dispatcher.py | pending |
| 0.3 | Delete companion/state.py | pending |
| 0.4 | Delete companion/startup.py | pending |
| 0.5 | Delete companion/events.py | pending |
| 0.6 | Delete companion/config.py | pending |
| 0.7 | Delete core/agents/chat.py | pending |
| 0.8 | Delete remora_demo/companion/ | pending |

## Phase 1: New Events

| # | Task | Status |
|---|------|--------|
| 1.1 | Write companion/events.py (NodeAgent* events) | pending |

## Phase 2: New Config

| # | Task | Status |
|---|------|--------|
| 2.1 | Write companion/config.py (Cairn required) | pending |

## Phase 3: Node Workspace

| # | Task | Status |
|---|------|--------|
| 3.1 | Write companion/node_workspace.py | pending |

## Phase 4: MicroSwarms

| # | Task | Status |
|---|------|--------|
| 4.1 | Write companion/swarms/__init__.py | pending |
| 4.2 | Write companion/swarms/base.py | pending |
| 4.3 | Write companion/swarms/summarizer.py | pending |
| 4.4 | Write companion/swarms/categorizer.py | pending |
| 4.5 | Write companion/swarms/linker.py | pending |
| 4.6 | Write companion/swarms/reflection.py | pending |

## Phase 5: Links

| # | Task | Status |
|---|------|--------|
| 5.1 | Write companion/links/types.py | pending |
| 5.2 | Write companion/links/resolver.py | pending |

## Phase 6: Sidebar Composer

| # | Task | Status |
|---|------|--------|
| 6.1 | Write companion/sidebar/composer.py | pending |

## Phase 7: NodeAgent

| # | Task | Status |
|---|------|--------|
| 7.1 | Write companion/node_agent.py | pending |

## Phase 8: Registry

| # | Task | Status |
|---|------|--------|
| 8.1 | Write companion/registry.py | pending |

## Phase 9: Router

| # | Task | Status |
|---|------|--------|
| 9.1 | Write companion/router.py | pending |

## Phase 10: Startup

| # | Task | Status |
|---|------|--------|
| 10.1 | Write companion/startup.py | pending |
| 10.2 | Write companion/__init__.py | pending |

## Phase 11: LSP Integration

| # | Task | Status |
|---|------|--------|
| 11.1 | Write lsp/handlers/companion.py | pending |
| 11.2 | Update lsp/server_setup.py | pending |

## Phase 12: __main__.py Wiring

| # | Task | Status |
|---|------|--------|
| 12.1 | Update lsp/__main__.py: CairnWorkspaceService init | pending |
| 12.2 | Update lsp/__main__.py: pass to _run_server() | pending |
| 12.3 | Update lsp/__main__.py: _on_initialized subscriber | pending |

## Phase 13: Tests

| # | Task | Status |
|---|------|--------|
| 13.1 | Write tests/unit/companion/test_node_workspace.py | pending |
| 13.2 | Write tests/unit/companion/test_swarms.py | pending |
| 13.3 | Write tests/unit/companion/test_node_agent.py | pending |
| 13.4 | Write tests/unit/companion/test_registry.py | pending |
| 13.5 | Run full test suite — confirm passes | pending |
| 13.6 | Run tach check — confirm 0 violations | pending |

## Phase 14: Neovim Plugin

| # | Task | Status |
|---|------|--------|
| 14.1 | Rewrite remora_demo/companion/nvim/lua/companion/init.lua | pending |
