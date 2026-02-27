# System Architecture

## Core Runtime

The runtime centers on a graph executor that coordinates agents while respecting
dependencies. A shared event bus carries tool calls, model responses, and lifecycle
events to the UI. Context is built from recent actions and prior summaries so that
agents can build on one another’s work.

## Workspace Model

Each graph has a stable workspace that mirrors the project. Individual agents get
copy-on-write workspaces layered on top, keeping writes isolated until the run is
complete. This design prevents one agent from clobbering another and makes it easy
to inspect outcomes per agent.

## Service Interface

The service exposes REST endpoints for planning and running graphs, plus SSE streams
for live UI updates. Optional event sourcing stores every event for replay, allowing
long-running sessions to be audited after the fact.
