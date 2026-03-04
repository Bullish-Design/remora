# Progress — Close Architecture Gaps

| Step | Description | Status |
|------|-------------|--------|
| 1 | Gap #2: Add `tags` to `AgentCompleteEvent` | done |
| 2 | Gap #1: Wire EventStore trigger consumption in LSP mode | done |
| 3 | Gap #3: Verify swarm tools end-to-end | done |
| 4a | Gap #4a: NodeProjection returns follow-up events; EventStore re-appends them | done |
| 4b | Gap #4b: ScaffoldRequestEvent routing via `to_agent` + subscriptions | done |
| 4c | Gap #4c: Pass scaffold_context to `_build_prompt()` for ScaffoldRequestEvent | done |
| 4d | Gap #4d: Pass `tags=("scaffold",)` on AgentCompleteEvent (SwarmExecutor + LSP Runner) | done |
| 5 | Bugfixes: Add `to_agent=` to all ScaffoldRequestEvent constructors | done |
| 6 | Full test suite — zero regressions confirmed | done |
