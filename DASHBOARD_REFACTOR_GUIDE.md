## Dashboard Refactor Guide

### 1) Symptoms + Current Behavior
- `remora-dashboard run` starts the server, but the browser shows a blank page at `/`.
- The `/subscribe` SSE endpoint returns HTML patches, yet the initial HTML render is empty.
- Dashboard styling does not apply, even when content renders (class attributes are not valid).
- Bundle selection in the UI does not line up with how bundles are actually keyed in config.

### 2) Root Cause of the Blank Page
Step-by-step trace:
1. `dashboard_view()` builds `header` and `main` HTML and returns `page(header + main)` in `src/remora/dashboard/views.py`.
2. `page()` is defined as `page(title="Remora Dashboard", *body_content)` in `src/remora/dashboard/views.py`.
3. Because `page()` receives a single positional argument, it is treated as the `title` argument, not body content.
4. Result: the UI HTML is injected into `<title>...</title>`, while `<body>` is empty.
5. The browser therefore renders a blank page even though the HTML string is non-empty.

Evidence you can confirm locally:
- A call to `dashboard_view()` produces HTML where the `<title>` tag contains `<div class_="header">...` and `<body>` is empty.
- This is the direct output of `src/remora/dashboard/views.py` and does not require SSE to reproduce.

### 3) Additional Issues That Block a “Solid” Dashboard
- **Invalid CSS class attributes**: `render_tag()` writes `class_="..."` not `class="..."` in `src/remora/dashboard/views.py`. The UI renders unstyled and looks broken even when content appears.
- **Bundle selector mismatch**: the UI prompts for bundle names like `lint`, but config bundles are keyed by node type (e.g. `function`, `class`) in `remora.yaml`. This makes dashboard runs confusing and hard to use.
- **Context builder duplication**: `GraphExecutor` always subscribes to the EventBus; the dashboard reuses the same `ContextBuilder`, so each run multiplies subscriptions (`src/remora/executor.py`). This causes duplicated context, memory growth, and skewed summaries over time.
- **No graph-level state handling**: `DashboardState` does not handle `GraphCompleteEvent` or `GraphErrorEvent` (`src/remora/dashboard/state.py`), so runs can appear “in progress” even when finished or failed.
- **Overly heavy rendering**: `/subscribe` sends a full-page patch on every event in `src/remora/dashboard/views.py`. This is expensive and makes the UI sluggish as event volume increases.
- **Remote JS dependency**: Datastar is loaded from a CDN. If the environment blocks external scripts, the interactive updates never run and the page appears inert.

### 4) Refactor Plan (Phased, Step-by-Step)

#### Phase 0: Restore Basic Rendering (fast, unblocks usage)
1. Fix the `page()` call in `src/remora/dashboard/views.py` so body content is passed as body content.
2. Update `render_tag()` to map `class_` → `class` and `for_` → `for`, and allow literal `data-*` attributes without rewriting.
3. Add a tiny unit test that asserts `<body>` includes “Remora Dashboard” for `dashboard_view()` output.
4. Add a local static fallback for Datastar (e.g. serve a vendored JS bundle under `/static/`) for offline use.

#### Phase 1: State Model and Event Consistency
1. Expand `DashboardState` in `src/remora/dashboard/state.py` to track:
   - Multiple graphs by `graph_id` (history + active run).
   - Graph completion/failure status.
   - Agent name (`node_name`) and timestamps/durations.
2. Handle `GraphCompleteEvent`, `GraphErrorEvent`, and `AgentSkippedEvent` in state.
3. Ensure each run initializes a new state record and does not clobber in-progress runs.
4. Add a `ContextBuilder` subscription toggle in `GraphExecutor` so the dashboard can manage it explicitly.

#### Phase 2: API Surface for a Real Dashboard
1. Add JSON endpoints (example path names; keep final names consistent with the rest of Remora):
   - `GET /api/state` for current dashboard state snapshot.
   - `GET /api/runs` for list of runs (history).
   - `GET /api/runs/{graph_id}` for details and agent status.
   - `POST /api/run` with structured options (target, node types, bundle key, max turns, etc).
   - `POST /api/cancel/{graph_id}` to cancel a running graph.
2. Validate run requests (target path exists, bundle key exists, node types known).
3. Include `config`-driven defaults in the UI (bundle mapping, discovery languages, concurrency).
4. Create a `RunRegistry` or similar in `src/remora/dashboard/` to own in-memory runs and tasks.

#### Phase 3: UI Restructure (Readable, Maintainable, Expandable)
1. Split the single giant `views.py` into:
   - `layout.py` (base HTML + assets)
   - `components.py` (rendering small UI fragments)
   - `routes.py` (request handlers + SSE)
2. Build UI components for:
   - Run list + run detail panel
   - Graph visualization (nodes + dependencies)
   - Agent timeline + status
   - Event log with filtering/search
   - Result summaries + errors
   - Human input panel
3. Replace “full-page patch per event” with partial patches:
   - Patch only the panels that changed (events, status, progress).
4. Ensure all dynamic content is HTML-escaped before rendering.

#### Phase 4: Execution UX Improvements
1. Run configuration UI:
   - Select bundle by node type, not by free-form string.
   - Optionally allow node-type filters and language filters.
   - Show estimated node count before starting.
2. Run management:
   - Cancel running graphs.
   - Retry failed agents.
   - Download result summaries and workspace diffs.
3. Show per-agent details:
   - Input prompt snippet
   - Tool calls + outputs
   - Workspace changes (diff or file list)

#### Phase 5: Testing + QA
1. Add unit tests for:
   - `dashboard_view()` HTML structure (body content non-empty).
   - `render_tag()` attribute normalization.
2. Add integration tests for:
   - `/api/state` and `/api/runs` output correctness.
   - SSE patch updates for agent start/complete/error.
   - Cancelling an in-flight run.
3. Manual QA checklist:
   - Start run → see graph + agent updates.
   - Inject human input → unblock agent.
   - Fail an agent → progress shows failed count.
   - Refresh page → state reconstructs correctly.

### 5) Recommended Implementation Order
1. Phase 0 fixes to make the current UI visible.
2. Phase 1 state-model improvements to make runs reliable.
3. Phase 2 API surface for a proper frontend.
4. Phase 3 UI split for maintainability.
5. Phase 4 UX improvements and graph visualization.
6. Phase 5 tests and QA hardening.

### 6) Key Files to Touch
- `src/remora/dashboard/views.py` (rendering, routing, page structure)
- `src/remora/dashboard/state.py` (state model + event handling)
- `src/remora/dashboard/app.py` (initialization, lifecycle, subscriptions)
- `src/remora/executor.py` (context builder subscription policy)
- `src/remora/event_bus.py` (streaming semantics; optional filtering)
- `remora.yaml` (bundle mapping + discovery defaults surfaced to UI)
