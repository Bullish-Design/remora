# Companion Demo — Progress Tracker

> **CRITICAL RULES:**
> - **NO SUBAGENTS** — Do ALL work directly.
> - **NEVER STOP AFTER COMPACTION** — Resume immediately.

---

## Status: CORE DEMO COMPLETE ✅

The Companion demo is now functional with all core components implemented and tested.

---

## Phase 0: Infrastructure

| Task | Status | Notes |
|------|--------|-------|
| 0.1 Set up project structure | ✅ Complete | `remora_demo/companion/` |
| 0.2 Define workspace schema | ✅ Complete | dataclass models in `models/` |
| 0.3 Set up sqlite-vec | ✅ Complete | Replaced ChromaDB, lighter |
| 0.4 Set up sentence-transformers | ✅ Complete | Configurable model |
| 0.5 Create indexing pipeline | ✅ Complete | chunker, embedder, store, indexer |
| 0.6 Create agent base class | ✅ Complete | `@subscribe` decorator |
| 0.7 Web clipper integration | Pending | Browser clip → markdown → embed |

## Phase 1: Sensors

| Task | Status | Notes |
|------|--------|-------|
| 1.1 cursor_tracker agent | ✅ Complete | Debounced, linger detection |
| 1.2 edit_tracker agent | ✅ Complete | Coalesced edits |
| 1.3 file_watcher agent | Pending | |
| 1.4 session_clock agent | ✅ Complete | Periodic ticks |

## Phase 2: Extractors

| Task | Status | Notes |
|------|--------|-------|
| 2.1 context_extractor agent | ✅ Complete | Text region, content type, structure |
| 2.2 term_extractor agent | Pending | Grail script |
| 2.3 structure_parser agent | Pending | AST/heading |
| 2.4 edit_summarizer agent | Pending | |

## Phase 3: Searchers

| Task | Status | Notes |
|------|--------|-------|
| 3.1 embedding_searcher agent | ✅ Complete | Vector similarity search |
| 3.2 term_definer agent | Pending | |
| 3.3 vault_linker agent | Pending | Obsidian integration |
| 3.4 reference_finder agent | Pending | Local cache |

## Phase 4: Analyzers

| Task | Status | Notes |
|------|--------|-------|
| 4.1 task_inferrer agent | Pending | Pattern detection |
| 4.2 connection_finder agent | ✅ Complete | Test/doc/concept connections |
| 4.3 question_generator agent | Pending | |
| 4.4 claim_checker agent | Pending | Prose only |

## Phase 5: Composers

| Task | Status | Notes |
|------|--------|-------|
| 5.1 sidebar_composer agent | ✅ Complete | Markdown composition |
| 5.2 session_summarizer agent | Pending | |
| 5.3 vault_writer agent | Pending | |
| 5.4 Sidebar markdown template | ✅ Complete | Inline in composer |

## Phase 6: Runtime & Integration

| Task | Status | Notes |
|------|--------|-------|
| 6.1 CompanionRuntime class | ✅ Complete | Wires all agents together |
| 6.2 LSP server | ✅ Complete | `lsp/server.py` - pygls based |
| 6.3 Neovim plugin | ✅ Complete | `nvim/lua/companion/init.lua` |
| 6.4 CLI entry point | ✅ Complete | `companion-lsp` command |

## Phase 7: Debug Timeline

| Task | Status | Notes |
|------|--------|-------|
| 7.1 Activation logging | ✅ Complete | In AgentBase |
| 7.2 Timeline server | ✅ Complete | `timeline/server.py` |
| 7.3 Web visualization | ✅ Complete | Embedded HTML/JS |
| 7.4 WebSocket updates | Pending | Currently uses polling |

## Phase 8: Testing & Polish

| Task | Status | Notes |
|------|--------|-------|
| 8.1 E2E test script | ✅ Complete | `test_e2e.py` |
| 8.2 Component unit tests | Partial | Inline tests work |
| 8.3 Performance tuning | Pending | Embedding model is slow |
| 8.4 Error handling | Partial | Basic error handling |
| 8.5 Demo script prep | Pending | |
| 8.6 Documentation | Partial | README for nvim plugin |

---

## Change Log

### 2026-03-03 (Session 3 - Current)

- Created `lsp/server.py` - full LSP server with pygls
- Created `nvim/lua/companion/init.lua` - Neovim plugin
- Created `nvim/README.md` - plugin documentation
- Created `agents/analyzers/connection_finder.py` - magic connection agent
- Created `timeline/server.py` - web visualization for debugging
- Created `test_e2e.py` - E2E test script
- Updated `runtime.py` to wire ConnectionFinder
- Added `companion-lsp` CLI entry point to pyproject.toml
- All core components tested and working

### 2026-03-03 (Session 2)

- Verified all core components working
- Full pipeline tested: cursor → context → search → sidebar

### 2026-03-03 (Session 1)

- Created detailed PLAN.md with full architecture
- Defined 15 agents across 5 layers
- **Phase 0-5 core complete:**
  - All infrastructure (sqlite-vec, embedder, chunker, indexer)
  - Core sensors (cursor_tracker, edit_tracker, session_clock)
  - Core agents (context_extractor, embedding_searcher, sidebar_composer)
  - Runtime wiring

---

## Files Created (This Session)

```
remora_demo/companion/
├── lsp/
│   ├── __init__.py              # Updated with exports
│   └── server.py                # ✅ NEW - Full LSP server
├── nvim/
│   ├── lua/companion/
│   │   └── init.lua             # ✅ NEW - Neovim plugin
│   └── README.md                # ✅ NEW - Plugin docs
├── agents/analyzers/
│   ├── __init__.py              # Updated with exports
│   └── connection_finder.py     # ✅ NEW - Connection agent
├── timeline/
│   ├── __init__.py              # Updated with exports
│   └── server.py                # ✅ NEW - Web visualization
├── runtime.py                   # Updated to wire ConnectionFinder
└── test_e2e.py                  # ✅ NEW - E2E test script
```

---

## Quick Commands

```bash
# Install companion extras
devenv shell -- uv sync --extra companion

# Verify imports
devenv shell -- uv run python -c "
from remora_demo.companion.lsp import CompanionLanguageServer
from remora_demo.companion.timeline import TimelineServer
from remora_demo.companion.agents.analyzers import ConnectionFinder
print('All imports OK!')
"

# Run E2E test (note: slow due to embedding model loading)
devenv shell -- uv run python -m remora_demo.companion.test_e2e

# Start LSP server manually
companion-lsp --workspace /path/to/project --debug
```

---

## Architecture Summary

```
┌─────────────────────────────────────────────────────────────┐
│                     Neovim Editor                           │
│  companion.nvim sends $/companion/cursorMoved on CursorHold │
└────────────────────────┬────────────────────────────────────┘
                         │ LSP
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                  CompanionLanguageServer                     │
│  - Receives cursor notifications                             │
│  - Manages CompanionRuntime                                  │
│  - Serves sidebar on request                                 │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                    CompanionRuntime                          │
│  Wires agents together, manages workspace                    │
└────────────────────────┬────────────────────────────────────┘
                         │
         ┌───────────────┼───────────────┐
         ▼               ▼               ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ CursorTracker│ │ EditTracker  │ │ SessionClock │
│   (sensor)   │ │   (sensor)   │ │   (sensor)   │
└──────┬───────┘ └──────────────┘ └──────────────┘
       │ CursorMoved event
       ▼
┌──────────────────────────────────────────────────────────────┐
│                     InMemoryWorkspace                         │
│  /companion/context/* ──→ ContextExtractor writes            │
│  /companion/search/*  ──→ EmbeddingSearcher writes           │
│  /companion/analysis/*──→ ConnectionFinder writes            │
│  /companion/output/*  ──→ SidebarComposer writes             │
└──────────────────────────────────────────────────────────────┘
       │ PathChanged events trigger agent cascade
       ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│ContextExtract│───▶│EmbeddingSearch│───▶│ConnectionFind│
└──────────────┘    └──────────────┘    └──────┬───────┘
                                               │
                                               ▼
                                        ┌──────────────┐
                                        │SidebarCompose│
                                        └──────┬───────┘
                                               │
                                               ▼
                                    /companion/output/sidebar.md
```

---

## What's Left (Nice to Have)

1. **Performance**: Use smaller/faster embedding model
2. **Vault integration**: Write sidebar to Obsidian vault
3. **More analyzers**: task_inferrer, question_generator
4. **WebSocket updates**: Real-time timeline without polling
5. **Web clipper**: Browser extension integration

---

> **REMINDER:**
> - **NO SUBAGENTS** — Do ALL work directly.
> - **NEVER STOP AFTER COMPACTION** — Resume immediately.
