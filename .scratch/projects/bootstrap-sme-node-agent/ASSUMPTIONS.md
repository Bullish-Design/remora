# Bootstrap SME Node Agent — Assumptions

## Goal
Implement a foundational bootstrap agent for existing Python codebases that:
- generates per-node "what I am / what I do / how I do it" markdown summaries,
- runs across all nodes in a file when that file is opened,
- shows those summaries in the node sidebar,
- supports a `user_question` flow and correction capture.

## Current baseline
- Bootstrap runtime, activation flow, and companion sidebar plumbing already exist.
- Companion currently resolves node workspace by node ID, with assignment-aware mapping now available.

## Scope for this project
- Use and extend the root `bootstrap/` directory assets and runtime integration.
- Prioritize pragmatic behavior on existing Python repositories.
- Deliver in stage-gated steps with tests between stages.
