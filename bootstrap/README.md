# bootstrap/ - Runtime Data for Bootstrap

This directory contains runtime data files consumed by the Python bootstrap
runtime in `src/remora/bootstrap/`.

## Contents

### `tools/` (`*.pym`)

Grail tool scripts exposed to bootstrap agents:

- `read_file.pym`, `write_file.pym` - agent workspace file IO
- `graph_node.pym`, `graph_neighbors.pym`, `graph_find_nodes.pym` - graph reads
- `graph_add_node.pym`, `graph_add_edge.pym` - graph writes
- `read_recent_events.pym`, `emit_event.pym` - event bus access
- `user_question.pym` - request human input through events

These call bedrock externals implemented in `src/remora/bootstrap/bedrock.py`.

### `agents/` (`*.yaml`)

Bootstrap schema defaults:

- `DEFAULT_SCHEMA.yaml` - fallback schema for new empty workspaces
- `base_code_agent.yaml` - baseline schema for code-node agents
- `coordinator.yaml` - target schema for a future LLM coordinator (currently aspirational)

Agent workspaces can override these by writing their own `schema.yaml`.

## Relationship to `src/remora/bootstrap/`

- `src/remora/bootstrap/` = Python runtime engine
- `bootstrap/` = runtime data loaded by that engine
