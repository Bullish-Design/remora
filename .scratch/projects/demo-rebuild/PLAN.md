# PLAN — Demo Rebuild

> **DO NOT USE SUBAGENTS. EVER. Do all work directly. No Task tool, no delegation, no spawning agents. This is non-negotiable.**

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
| T1 | Create configlib demo project source files | pending |
| T2 | Create .remora/models/ extension configs + remora.yaml | pending |
| T14 | Implement enhanced MockLLMClient with scripted responses | pending |
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

## Execution Order

1. T1, T2 — Demo project files (quick, establishes the test bed)
2. T14 — MockLLMClient (largest independent task, net-new code)
3. T15, T16, T17, T18 — Graph viewer foundations (all independent)
4. T20 — View functions (compose layout + SVG + CSS)
5. T19 — Stario app (wire views into endpoints)
6. T21 — Entry points + launcher
7. T22 — Integration test

---

> **REMINDER: DO NOT USE SUBAGENTS. Do all work directly. No Task tool, no delegation, no spawning agents. Work inline, in this session, yourself.**
