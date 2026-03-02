# Option A: LSP→EventStore Unification — Decisions

## pending_proposal_id: Removed from AgentNode
- **Assumption**: Proposals are operational state, not node identity.
- **Decision**: Track proposals via the `proposals` table `status` column in RemoraDB. AgentNode doesn't carry proposal references.

## Status value alignment: active→idle, orphaned→removed
- **Assumption**: Core uses `idle/running/error/pending_approval`. LSP used `active/orphaned/running/pending_approval`.
- **Decision**: Map `active`→`idle`. Replace `orphaned` with `NodeRemovedEvent` instead of a status value.

## remora_id → node_id
- **Assumption**: All code should use a single consistent identifier name.
- **Decision**: AgentNode uses `node_id`. All LSP code migrated. The `# rm_xxxxx` comment format in source files stays — it's a display format, not a field name.

## RemoraDB scope: edges stay, nodes move
- **Assumption**: Graph topology (edges) is LSP-specific operational data. Node identity is core.
- **Decision**: RemoraDB keeps edges, proposals, cursor_focus, command_queue, events, activation_chain. Nodes table deleted.

## LazyGraph: dual DB connections
- **Assumption**: LazyGraph needs both node and edge data. After migration they live in different databases.
- **Decision**: LazyGraph takes two DB paths — EventStore's DB for nodes, RemoraDB for edges. Fixed critical bug: empty `rx.PyDiGraph()` is falsy in Python, so all guards use `self.graph is None` instead of `not self.graph`.

## LSP event models: keep in lsp/models.py
- **Assumption**: AgentEvent, HumanChatEvent, etc. are LSP-specific wrappers, not core node state.
- **Decision**: Keep them. They handle the LSP↔core event bridge. Removing ASTAgentNode doesn't affect them.

## lsp/extensions.py ExtensionNode: deleted
- **Decision**: Replaced by `src/remora/extensions.py` AgentExtension. Single extension system.

## full_name computation
- **Decision**: Computed as `{stem}.{name}` for functions, `{stem}.{class}.{method}` for methods, `{stem}` for files. Watcher computes it at parse time.
