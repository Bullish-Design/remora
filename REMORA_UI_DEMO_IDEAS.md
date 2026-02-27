# Remora UI Demo Ideas

## Remora capabilities an external app can use

- HTML shell at `GET /` with Datastar init pointing to `/subscribe`.
- Datastar SSE patch stream at `GET /subscribe` for UI updates.
- Raw SSE event stream at `GET /events` with normalized envelopes (`kind`, `type`, `graph_id`, `agent_id`, `timestamp`, `payload`).
- Graph execution at `POST /run` with optional `bundle` and `graph_id`.
- Human input flow at `POST /input` for `HumanInputRequestEvent` prompts.
- Plan preview at `POST /plan` to render a graph before execution.
- Sanitized config snapshot at `GET /config` (bundle mapping, discovery, model defaults).
- UI snapshot at `GET /snapshot` (events, blocked agents, progress, results, recent targets).
- Event kinds to drive UI panels: `graph`, `agent`, `tool`, `model`, `human`, `checkpoint`, `turn`.

## Demo ideas for a Stario reference app (separate repo)

### 1) Mission Control Graph Runner

Goal: A cinematic control room that visualizes the plan graph, live execution, and human input gates.

Pros:
- Shows the full run loop (plan -> run -> stream -> input).
- Highlights the event envelope model and progress reporting.

Cons:
- Graph visualization adds UI complexity.
- Needs careful batching to avoid UI thrash on fast streams.

Implementation outline:
- Use `POST /plan` to build the graph layout and show dependencies.
- Use `POST /run` and subscribe to `/events` for fine-grained updates.
- Use `/input` to resolve `HumanInputRequestEvent` with inline forms.
- Use `/snapshot` on initial page load as a quick baseline state.

### 2) Agentic Code Review Studio

Goal: A code review theater where agents annotate a file or folder, show evidence, and request human approvals.

Pros:
- Naturally fits Remora bundles (lint, docstring, tests, refactor).
- Great for demoing human-in-the-loop prompts.

Cons:
- Requires curated bundles and agent prompts to look polished.
- Needs a good sample repo to make results compelling.

Implementation outline:
- Let users pick a target file and bundle from `GET /config`.
- Run a graph and render per-agent cards from `AgentCompleteEvent`.
- Surface `ToolCallEvent` and `ModelResponseEvent` as evidence trails.
- Highlight human input questions in a dedicated approval panel.

### 3) Tool Call Observatory

Goal: A live visualization of tool usage, model calls, and outputs as a cascading timeline.

Pros:
- Makes tool-calling and model orchestration feel tangible.
- Shows off `tool` and `model` event kinds clearly.

Cons:
- Less intuitive for non-technical audiences.
- Requires enough tool activity to look interesting.

Implementation outline:
- Subscribe to `/events` and filter for `tool` and `model` kinds.
- Render a timeline view with expandable payload details.
- Provide a "replay" mode that replays buffered SSE events.

### 4) Multi-Graph Batch Runner

Goal: A batch execution console that can launch multiple graphs, compare durations, and aggregate results.

Pros:
- Demonstrates multi-run concurrency and `graph_id` handling.
- Useful for CI or large repos (scan many targets).

Cons:
- Needs careful UI to avoid being too dense.
- Requires run orchestration logic in the client.

Implementation outline:
- Allow queueing multiple `POST /run` requests with custom `graph_id`s.
- Track per-graph progress from `GraphStartEvent` and `GraphCompleteEvent`.
- Aggregate summaries and link to per-graph result panels.

### 5) Plan-Then-Approve Pipeline

Goal: A staged workflow where the user previews the plan, edits scope, then approves execution.

Pros:
- Emphasizes safe, agentic collaboration.
- Uses `/plan` in a tangible, user-driven way.

Cons:
- Requires extra UX for selecting nodes to run.
- Needs a clean way to filter nodes by bundle or type.

Implementation outline:
- Use `/plan` to show nodes and allow selection or filtering.
- Submit `/run` only after approval, with optional `bundle` filters.
- Display progress and results via `/events` and `/snapshot`.

