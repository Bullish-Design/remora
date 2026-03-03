# ASSUMPTIONS — Custom Node Extensions Demo

## Project Purpose

Demonstrate Remora's reactive event-driven architecture via three custom `AgentExtension` configs that showcase:
1. A node creating another node (cascading creation)
2. Cascading reactivity (changes propagate through multiple agents via events)
3. Meta-observation (agents watching other agents without being messaged)

## Audience

- Developers evaluating Remora's extension model
- The demo project (`remora_demo/project/`) serves as the reference showcase

## Constraints

- **AgentNode is a single Pydantic BaseModel** — no subclasses. Specialization is data via extensions.
- Extensions are pure data declarations: `matches()` + `get_extension_data()`.
- Extensions live in `.remora/models/*.py`. First match wins (alphabetical order by filename).
- The actual agent *behavior* comes from: system prompt (LLM instructions), extra_tools (callable tools), extra_subscriptions (reactive routing).
- For the e2e demo test, we don't call a real LLM. We test the extension matching, projection population, subscription routing, and cascade chain mechanics.

## Key Design Decisions

### 1. Extension files go in `remora_demo/project/.remora/models/`
These are demo/reference extensions. They live alongside the existing `test_function.py` and `package_init.py` extensions.

### 2. Filename prefixes control priority
Since first match wins in alphabetical order:
- `class_doc_generator.py` — matches classes
- `function_test_scaffold.py` — matches non-test functions
- `swarm_monitor.py` — matches MONITOR.md file nodes

These don't overlap with existing extensions (`package_init.py` matches `__init__.py` files, `test_function.py` matches `test_*` functions).

### 3. Extension data uses existing AgentNode fields
Each extension returns a dict with:
- `extension_name`: str identifier
- `custom_system_prompt`: LLM instructions for the agent's role
- `extra_tools`: list of `ToolSchema` dicts for additional capabilities
- `extra_subscriptions`: list of `SubscriptionPattern` dicts for reactive event routing

### 4. Test strategy
- **Unit tests**: Each extension's `matches()` and `get_extension_data()` return correct values
- **Integration tests**: Projection populates correct fields when these extensions are configured; subscription routing delivers events to the right agents
- **E2e cascade test**: Full chain from node discovered -> extension matched -> subscriptions registered -> event emitted -> correct agents triggered. Uses headless runner pattern (no LLM).

### 5. The three extensions — detailed specs

**ClassDocGenerator**
- `matches(node_type="class", name=any)` — all classes
- Creates `extra_tools` with a `create_doc_file` tool schema
- Subscribes to `NodeDiscoveredEvent` and `ContentChangedEvent` for its own file
- System prompt instructs: "When you're triggered, generate API documentation for your class and create a `docs/<classname>.md` file"

**FunctionTestScaffold**
- `matches(node_type="function", name=NOT "test_*")` — non-test functions
- Creates `extra_tools` with a `create_test_file` tool schema
- Subscribes to `NodeDiscoveredEvent` for its own file
- System prompt instructs: "When you're triggered, generate test stubs and create `tests/test_<module>.py`"

**SwarmMonitor**
- `matches(node_type="file", name="MONITOR.md")` — only the MONITOR.md file
- Subscribes to `ToolCallEvent`, `AgentErrorEvent`, `AgentCompleteEvent` (all agents — meta-observer)
- System prompt instructs: "You observe all agent activity. Log a summary of each event to your own file."
- No extra_tools needed — uses `rewrite_self` to append to its own content

### 6. No new core code required
The extensions are purely configuration. They use existing `AgentExtension`, `ToolSchema`, and `SubscriptionPattern` infrastructure. No changes to `extensions.py`, `agent_node.py`, `events.py`, `subscriptions.py`, or `projections.py`.
