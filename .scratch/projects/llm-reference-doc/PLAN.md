# LLM Reference Document — PLAN

**NO SUBAGENTS. Do all work directly.**

## Goal
Write a super condensed HOW TO USE reference document optimized for LLM consumption (not humans).

## Structure (user-specified order)
1. Why to use Remora
2. Theory of operation
3. High-level concepts
4. Detailed core components
5. API reference

## Steps
1. [DONE] Read architecture docs (EventBased_Concept, CONCEPT, ARCHITECTURE, SPEC)
2. [DONE] Read core source (events, subscriptions, extensions, config, discovery, agent_node)
3. Read remaining source (event_store, swarm_executor, reconciler, projections, chat, workspace, tools, lsp, cli)
4. Read remaining docs (API_REFERENCE, CONFIGURATION, HOW_TO_*, __init__.py)
5. Write TOC and save to file first
6. Write document section by section, appending to file

## Acceptance Criteria
- Dense, not verbose — optimized for machine consumption
- Top-down: why → theory → concepts → components → API
- Covers all core systems: EventLog, discovery, AgentNode, subscriptions, extensions, tools, reactive loop, LSP

**NO SUBAGENTS. Do all work directly.**
