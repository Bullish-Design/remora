# PLAN — Demo Rebuild

> **DO NOT USE SUBAGENTS. EVER. Do all work directly. No Task tool, no delegation, no spawning agents. This is non-negotiable.**

> **ALWAYS CONTINUE AFTER COMPACTION. This project must be completed in full — fully integrated, fully tested, ready to demo. After every compaction or session restart, read CRITICAL_RULES.md, then this project's CONTEXT.md and PROGRESS.md, and IMMEDIATELY resume working on the next pending task. Do NOT wait for user input. Do NOT stop until every task in this plan is marked done. This is an absolute requirement.**

Rebuild `remora_demo/` from scratch based on `EVENT_BASED_DEMO_PLAN.md`, adapted for the two-subdirectory architecture (neovim/ + web/).

## Directory Structure

```
remora_demo/
  project/                    # configlib demo project (shared)
    remora.yaml
    .remora/models/
      test_function.py
      package_init.py
    src/configlib/
      __init__.py
      loader.py
      schema.py
      merge.py
    tests/
      test_loader.py
      test_merge.py
  neovim/                     # Neovim + LSP demo (Python 3.13)
    devenv.nix                # (or uses parent devenv)
    mock_llm.py               # Enhanced MockLLMClient
    __main__.py               # Entry point for LSP demo
  web/                        # Stario graph viewer (Python 3.14)
    devenv.nix
    graph/
      __init__.py
      __main__.py             # Entry point
      app.py                  # Stario app factory
      bridge.py               # DB->Relay polling bridge
      layout.py               # Server-side force layout
      svg.py                  # SVG element builders
      css.py                  # Catppuccin dark theme
      views/
        __init__.py
        shell.py              # Full HTML page
        graph.py              # SVG graph rendering
        sidebar.py            # Sidebar detail panel
        event_stream.py       # Global event stream
  launch.sh                   # Convenience launcher (starts both)
```

## Task List (adapted from EVENT_BASED_DEMO_PLAN.md Section 14)

### Phase A: Foundations (independent, can run in parallel)

| ID | Task | Status |
|----|------|--------|
| T1 | Create configlib demo project source files | **done** |
| T2 | Create .remora/models/ extension configs + remora.yaml | **done** |
| T14 | Implement enhanced MockLLMClient with scripted responses | **done** |
| T15 | Implement server-side ForceLayout (layout.py) | pending |
| T16 | Implement SVG element builders (svg.py) | pending |
| T17 | Implement CSS theme + transitions (css.py) | pending |
| T18 | Implement DB->Relay polling bridge (bridge.py) | pending |

### Phase B: Wiring (depends on Phase A)

| ID | Task | Status |
|----|------|--------|
| T20 | Implement view functions (shell, graph, sidebar, event_stream) | pending |

### Phase C: Assembly

| ID | Task | Status |
|----|------|--------|
| T19 | Implement Stario app + handlers (app.py) | pending |

### Phase D: Integration

| ID | Task | Status |
|----|------|--------|
| T21 | Implement demo entry points + launcher | pending |
| T22 | End-to-end integration test (golden path smoke test) | pending |

### Skipped Tasks (already done via Option A)

T3-T13 (Core Migration) — Option A unification is complete. AgentNode and EventStore are already wired into the LSP subsystem. Some cleanup may be needed but these are not part of the demo rebuild scope.

## Execution Order (Remaining)

1. **T15** — ForceLayout (server-side force-directed graph positioning)
2. **T16** — SVG builders (node circles, edges, labels, status indicators)
3. **T17** — CSS theme (Catppuccin dark, CSS transitions for smooth animation)
4. **T18** — DB->Relay bridge (poll SQLite every 300ms, fingerprint, publish changes)
5. **T20** — View functions (compose layout + SVG + CSS into HTML fragments)
6. **T19** — Stario app (wire views into HTTP endpoints, SSE/Datastar push)
7. **T21** — Entry points + launcher (remora_demo/web/graph/__main__.py, launch.sh)
8. **T22** — Integration test (golden path smoke test)

## Pre-Implementation Checklist

Before starting T15, need to:
- [ ] Verify Stario is available as a dependency (pyproject.toml or separate install)
- [ ] Read EVENT_BASED_DEMO_PLAN.md Sections 7-11 for graph viewer specs
- [ ] Read EventStore API to understand what data the bridge needs to poll

## TDD Approach

Each task follows: write failing test -> implement -> verify test passes.
Tests for graph viewer components go in `tests/demo/web/` or alongside the modules.

---

> **REMINDER: DO NOT USE SUBAGENTS. Do all work directly. No Task tool, no delegation, no spawning agents. Work inline, in this session, yourself.**

> **REMINDER: ALWAYS CONTINUE AFTER COMPACTION. Do NOT wait for user input. Read CONTEXT.md, check PROGRESS.md, pick up the next pending task, and keep going until the entire project is done.**
