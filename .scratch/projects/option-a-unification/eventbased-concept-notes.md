# Scratch Notes: EventBased_Concept.md
# STATUS: COMPLETE - 838 lines, all 5 perspectives, verified against source code
# LOCATION: docs/EventBased_Concept.md
# NOT YET COMMITTED

## Document Structure (Approach B: Architecture Core + Five Lenses)
1. Header + intro (supersedes V2.1 with backref)
2. Architecture Core (EventLog, subscriptions, discovery, reactive loop)
3. Perspective 1: User (Neovim experience)
4. Perspective 2: Developer (creating apps with Remora)
5. Perspective 3: Agent (multi-agent comms, CSTNode current+aspirational)
6. Perspective 4: Node (lifecycle of a single CSTNode instance)
7. Perspective 5: Environment (library-spawning swarm, full configs)
8. LSP Integration Summary (backref to V2.1)
9. Future: Aspirational CSTNode Types

## Key Architecture Facts

### Event Types (events.py)
- Agent events: AgentStartEvent, AgentCompleteEvent, AgentErrorEvent
- Human-in-loop: HumanInputRequestEvent, HumanInputResponseEvent
- Reactive swarm: AgentMessageEvent, FileSavedEvent, ContentChangedEvent, ManualTriggerEvent
- Kernel re-exports: KernelStartEvent, KernelEndEvent, ToolCallEvent, ToolResultEvent, ModelRequestEvent, ModelResponseEvent, TurnCompleteEvent
- Union type: RemoraEvent

### SubscriptionPattern (subscriptions.py)
- 5 dimensions: event_types, from_agents, to_agent, path_glob, tags
- All optional (None = match anything)
- SQLite-backed SubscriptionRegistry
- Default subs: direct message (to_agent=self) + file changes (ContentChangedEvent for agent's file)
- get_matching_agents(event) returns all agent_ids whose subs match

### CSTNode (discovery.py)
- Frozen dataclass: node_id, node_type, name, full_name, file_path, text, start_line, end_line, start_byte, end_byte
- node_id = SHA256(file_path:name:start_line:end_line)[:16]
- node_types: file, class, function, method, section, table
- Languages: python, markdown, toml (+ yaml, json, js, ts, go, rust in LANGUAGE_EXTENSIONS but no queries yet)
- Tree-sitter queries in queries/{language}/remora_core/*.scm
- Python: function.scm (method.def + function.def), class.scm (class.def), file.scm (file.def)
- Markdown: section.scm (section.def = ATX headings, code_block.def), file.scm
- TOML: table.scm (table.def, array_table.def), file.scm

### ExtensionNode (extensions.py)
- Pydantic BaseModel subclass
- matches(node_type, name) -> bool
- system_prompt property, get_workspaces(), get_tool_schemas()
- Loaded from .remora/models/*.py
- Mtime-based caching

### AgentState (agent_state.py)
- Fields: agent_id, node_type, name, full_name, file_path, parent_id, range, connections, chat_history, custom_subscriptions, last_updated
- JSONL persistence (append-only, read last line)

### Config (config.py)
- Key fields: discovery_paths, bundle_root, bundle_mapping, bundle_mapping_tools
- model_base_url, model_default, model_api_key
- max_concurrency=4, max_turns=8, max_trigger_depth=5, trigger_cooldown_ms=1000
- swarm_root=".remora"

### Swarm Tools (tools/swarm.py)
- 5 built-in tools: send_message, subscribe, unsubscribe, broadcast, query_agents
- broadcast patterns: "children", "siblings", "file:/path"
- All use externals dict for emit_event, register_subscription, etc.

### Agent Runner (agent_runner.py)
- Consumes triggers from EventStore.get_triggers()
- Cascade safety: correlation_id tracking, depth limits, cooldowns, semaphore
- Delegates to SwarmExecutor.run_agent()

### SwarmExecutor (swarm_executor.py)
- Resolves bundle via bundle_mapping[node_type]
- Loads manifest, initializes workspace (CairnWorkspaceService)
- Creates _EventStoreObserver for kernel events -> writes directly to EventStore
- Builds prompt with code context, trigger event, chat history
- Runs AgentKernel (structured-agents) with tools + messages

## Design Decisions from EVENT_ARCHITECTURE_ALIGNMENT.md
- EventLog (SQLite events table) is single source of truth
- EventBus TO BE DELETED
- EventStore TO BE DELETED (replaced by unified EventLog in RemoraDB)
- SwarmState TO BE DELETED
- Cursor: debounced event (200ms stable)
- Kernel events: FULL event treatment (subscription matching on ALL events)
- Schema versioning: JSON payloads, defaults on missing
- command_queue: keep as separate work queue

## V2.1 LSP Interactions (for backref section)
- LSP is the spine: Neovim -> Remora as language server
- Hover: agent status on code elements
- Code lens: inline agent actions
- Code actions: propose/accept/reject rewrites
- Diagnostics: proposals-as-diagnostics
- SSE: real-time agent activity in Nui sidebar
- Pydantic models bridge LSP <-> core

## Library-Spawning Swarm Example Plan
Need full config examples:
- Scaffold agent: reacts to project init, generates file structure
- Interface agent: reacts to scaffold output, creates function signatures
- Implementation agent: reacts to interfaces, fills in code
- Test agent: reacts to implementations, generates tests
- Validation agent: reacts to tests, runs and reports
- Docs agent: reacts to validated code, generates docstrings

Each needs: bundle.yaml, subscription patterns, event payloads, tool calls
