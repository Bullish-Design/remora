# Implementation Guide: Step 7 - Event-Based Human-in-the-Loop

## Target
Replace the polling-based IPC with `HumanInputRequestEvent`/`HumanInputResponseEvent` flowing through the unified EventBus so Grail `@external ask_user()` can block asynchronously waiting for responses.

## Overview
- Emit `HumanInputRequestEvent` from the Grail external implementation when an agent asks for human input.
- Dashboard listens to the EventBus stream, surfaces the question via SSE, and emits `HumanInputResponseEvent` when the user replies.
- The external uses `EventBus.wait_for()` to await the matching response event with a timeout, keeping IPC entirely in-process.

## Contract Touchpoints
- `ask_user_external()` emits `HumanInputRequestEvent` and awaits `EventBus.wait_for()` on the matching response.
- Dashboard SSE subscribes to request events and posts `HumanInputResponseEvent` via an HTTP endpoint.
- Events include `graph_id`, `agent_id`, and `request_id` for correlation across systems.

## Done Criteria
- Grail `ask_user()` blocks asynchronously until a response or timeout.
- Dashboard relays requests and emits responses through the EventBus.
- Executor wiring ensures the external has access to the shared EventBus.

## Steps
1. Define `HumanInputRequestEvent` and `HumanInputResponseEvent` in `events.py` (include `graph_id`, `agent_id`, `request_id`, `question`, `timestamp`).
2. Implement `ask_user_external(question: str)` in `interactive.py` (or a helper module) that emits the request event, waits on the bus via `wait_for()`, and returns the response.
3. Update the dashboard SSE stream (Step 11) to subscribe to `HumanInputRequestEvent`, push it to browsers, and expose an HTTP endpoint that emits `HumanInputResponseEvent` when users send answers.
4. Ensure `GraphExecutor`/`execute_agent()` wires the EventBus as the observer so the external has access to the shared bus and `wait_for()` functionality.
