# Option A: Full LSP→EventStore Unification Plan

## Decision Log

**Q: EventStore sync vs async?**
A: Already async. No barrier.

**Q: What about `pending_proposal_id`?**
A: Keep in RemoraDB proposals table. It's proposal-specific state, not node identity.
The LSP runner already queries `server.proposals[id]` from an in-memory dict.
AgentNode doesn't need this field — the proposals table links agent_id→proposal.

**Q: Status value alignment?**
A: Core uses "idle"/"running"/"error"/"pending_approval". LSP uses "active"/"orphaned"/"running"/"pending_approval".
Map: "active"→"idle", "orphaned"→removed (NodeRemovedEvent instead). Keep "running", "pending_approval", add "error".

**Q: `remora_id` vs `node_id`?**
A: AgentNode uses `node_id`. All LSP code migrates to `node_id`. The inject_ids function
writes `# rm_xxxxx` comments — the prefix stays, it's just a display format.

**Q: Missing `get_node_at_position` on EventStore?**
A: Add it. Simple query: WHERE file_path = ? AND start_line <= ? AND end_line >= ? ORDER BY (end_line - start_line) ASC LIMIT 1
(Narrowest containing node.)

**Q: Missing `full_name` in watcher?**
A: Compute as `{Path(file_path).stem}.{name}` for functions/methods, `{Path(file_path).stem}` for files, `{Path(file_path).stem}.{class_name}.{method_name}` for methods.

**Q: What about RemoraDB edges table?**
A: For now, keep edges in RemoraDB. The graph (LazyGraph) reads edges. This is graph topology, not node identity. Could migrate later but not blocking.

**Q: What about `inject_ids` writing `# rm_xxxx` comments?**
A: Keep inject_ids. It writes `node.node_id` (was `node.remora_id`). The IDs themselves are the same format (rm_xxxxx).

**Q: What about RemoraDB node operations that LSP still needs?**
A: After migration, RemoraDB keeps: proposals, cursor_focus, command_queue, events (LSP event log), activation_chain, edges. Nodes table moves to EventStore.

**Q: What happens to `lsp/extensions.py` ExtensionNode?**
A: Replaced by `extensions.py` AgentExtension. The runner.apply_extensions() switches to using AgentExtension + load_extensions() from core.

**Q: What about the lsp/models.py ToolSchema (Pydantic)?**
A: Replaced by core agent_node.py ToolSchema (dataclass). The Pydantic one has `to_llm_tool()` and `to_code_action()`. The dataclass one already has both. Delete the Pydantic version.

**Q: What about ASTAgentNode.from_agent_state()?**
A: Delete. AgentState is being removed in Phase 2 anyway.

**Q: What about the LSP event models (AgentEvent, HumanChatEvent, etc.)?**  
A: Keep them. They're LSP-specific event wrappers with `to_core_event()` converters. They live in lsp/models.py and handle the LSP↔core event bridge. Removing ASTAgentNode doesn't affect them.

**Q: What about LazyGraph which takes RemoraDB in constructor?**
A: LazyGraph reads from RemoraDB's nodes + edges tables. After migration, nodes are in EventStore. LazyGraph needs to read from EventStore for nodes and RemoraDB for edges. Simplest: give LazyGraph access to EventStore's DB path, or have it accept an EventStore. For now, keep it reading from RemoraDB edges only and get node data from EventStore.

## Execution Order (TDD, atomic commits)

### Task 1: Add `get_node_at_position()` to EventStore
- Test: query by file_path + line → returns narrowest AgentNode
- Impl: new async method on EventStore
- Commit

### Task 2: Add `set_node_status()` to EventStore  
- Test: update status of a node
- Impl: new async method (direct UPDATE, not event-sourced — status changes are projections of runtime events)
- Commit

### Task 3: Add `remove_nodes_for_file()` to EventStore
- Test: remove all nodes for a file_path (for orphan cleanup)
- Impl: new async method
- Commit

### Task 4: Update watcher to return dicts instead of ASTAgentNode
- Watcher currently returns `list[ASTAgentNode]`. Change to return `list[dict]` with fields matching NodeDiscoveredEvent.
- Actually: watcher should emit NodeDiscoveredEvents. But watcher is sync and doesn't have access to EventStore.
- Better: watcher returns lightweight dicts, the caller (documents.py) creates events and appends to EventStore.
- Test: existing watcher tests still pass with dict output
- Commit

### Task 5: Update documents.py handlers (did_open, did_save) to use EventStore
- Instead of `server.db.upsert_nodes(nodes)`, emit NodeDiscoveredEvents to EventStore
- Instead of `server.db.get_nodes_for_file(uri)`, call `event_store.list_nodes(file_path=uri)`
- Handle orphan detection via NodeRemovedEvent
- Commit

### Task 6: Update LSP handlers (lens, hover, actions) to use EventStore+AgentNode
- lens.py: `event_store.list_nodes()` → `AgentNode.to_code_lens()`
- hover.py: `event_store.get_node_at_position()` → `AgentNode.to_hover()`
- actions.py: same pattern
- Commit

### Task 7: Update commands.py to use EventStore+AgentNode
- All `ASTAgentNode(**node)` → `event_store.get_node(id)` returning AgentNode
- Commit

### Task 8: Update runner.py to use EventStore+AgentNode
- `execute_turn`: get AgentNode from EventStore
- `apply_extensions`: use AgentExtension from core
- `handle_response`: agent is AgentNode, use node_id instead of remora_id
- `get_agent_tools`: accept AgentNode
- Commit

### Task 9: Update notifications.py to use EventStore
- `on_cursor_moved`: use `event_store.get_node_at_position()`
- Commit

### Task 10: Update server.py  
- Remove ASTAgentNode import
- Remove ToolSchema import from lsp/models (use from core)
- `discover_tools_for_agent` accepts AgentNode
- Commit

### Task 11: Clean up lsp/models.py
- Remove ASTAgentNode class entirely
- Remove ToolSchema class (use core's)
- Keep: RewriteProposal, AgentEvent and subclasses, generate_id()
- Commit

### Task 12: Remove lsp/extensions.py
- Delete file
- Update runner.py to use core extensions.py
- Commit

### Task 13: Remove RemoraDB nodes table
- Remove upsert_nodes, get_node, get_nodes_for_file, get_all_nodes, get_node_at_position, set_status, _normalize_node from RemoraDB
- Remove nodes table from schema
- Keep: edges, proposals, cursor_focus, command_queue, events, activation_chain
- Update tests
- Commit

### Task 14: Update LazyGraph to work with EventStore for nodes
- LazyGraph currently reads nodes from RemoraDB. Needs to read from EventStore.
- Commit

### Task 15: Integration test — full LSP→EventStore pipeline
- Open file → watcher parses → events emitted → EventStore has nodes → handler reads AgentNode → LSP responses correct
- Commit

### Task 16: Clean up and final verification
- Run full test suite
- Remove any dead imports
- Commit
