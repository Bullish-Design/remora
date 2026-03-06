# Final Refactor: Brainstorming

## Inputs
- `code_review_report.md`: Identifies removing `watcher.py` (Opportunity A), fixing truncated file node context (Opportunity B), and direct event flow for DB edges (Opportunity C).
- `architectural_review_report.md`: Identifies removal of LSP leakage from `EventStore` (Opportunity A), optimizing node queries (Opportunity B), fixing `LazyGraph` DB coupling (Opportunity C), and decoupling `AgentRunner` from LSP specifics (Opportunity D).

## Core Principles
1. **Event-Driven Purity**: Services interact via Events.
2. **Layer Isolation**: `core` should not know about `lsp`, `companion`, or UI layers.
3. **No Backwards Compatibility**: If an API or abstraction is clunky, rewrite it or delete it.

## Brainstorming Topics

### 1. Removing `watcher.py` entirely (Code Review Opp A)
*How to handle this cleanly?*

### 2. LSP Data Leakage in `EventStore` (Arch Review Opp A)
*`proposals`, `command_queue`, `activation_chain` must move to `RemoraDB`.*

### 3. `LazyGraph` directly querying `EventStore` DB (Arch Review Opp C)
*How do we rewrite `LazyGraph` to be decoupled from physical SQL schema of Core?*

### 4. Splitting `AgentRunner` (Arch Review Opp D)
*How do we cleanly separate Swarm logic vs. LSP logic?*

### Additional Architectural Improvements
*What else should we change while we have carte blanche?*
