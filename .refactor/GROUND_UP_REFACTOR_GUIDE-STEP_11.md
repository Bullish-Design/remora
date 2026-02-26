# Implementation Guide: Step 11 - Dashboard Service

## Target
Split the former Hub server into `remora/dashboard/`, build a Starlette/SSE app that subscribes to the unified EventBus, reads from the shared indexer store, and orchestrates graph runs via the core executor.

## Overview
- The dashboard exposes an SSE stream that filters `RemoraEvent`s (graph lifecycle, kernel events, human I/O) for browser clients.
- It offers HTTP endpoints that read node metadata from `NodeStateStore`, trigger graph execution via `GraphExecutor`, and accept human-in-loop responses that emit `HumanInputResponseEvent`.
- Human questions from agents (Step 7) flow through the EventBus, the dashboard exposes them via SSE, and a REST endpoint posts answers back to the bus.

## Steps
1. Create `dashboard/app.py` with a Starlette app, event stream endpoint (`/events`) that uses `EventBus.stream()` to push typed events, and JSON endpoints for starting runs and returning node metadata.
2. Implement `dashboard/views.py` (or helpers) that wrap SSE responses and handle request/response mechanics, and `dashboard/state.py` for dashboard client tracking and graph status emission.
3. Provide `dashboard/cli.py` for the `remora-dashboard` entry point that reads config, starts the SSE app, and wires the EventBus to the executor for run requests.
4. Ensure the dashboard subscribes to `HumanInputRequestEvent` and returns those events via SSE, while `/answer` endpoint emits `HumanInputResponseEvent` for agent `wait_for()` calls.
