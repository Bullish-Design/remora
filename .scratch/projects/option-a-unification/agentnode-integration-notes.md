# AgentNode Integration Plan

## Decision: Option A (Materialized View) with data-driven specialization

AgentNode is a single Pydantic BaseModel. No subclasses. Specialization is expressed
as data fields (extension_name, custom_system_prompt, extra_tools, extra_subscriptions)
populated by extension configs at discovery time.

## DONE so far
- Section 1.7 (The AgentNode Model) - WRITTEN and inserted after 1.6
- Section 1.4 (Discovery) - Added "From CSTNode to AgentNode" subsection
- Section 3 (Developer) - Rewrote "Writing Extension Nodes" → "Writing Extension Configs" with 6 examples
- Section 4 (Agent) - Updated identity pipeline, broadcasting, CSTNode types subsection
- Section 5 (Node Lifecycle) - Replaced AgentState with AgentNode throughout (projection, hydration, status updates, death)
- Section 6 (Environment) - Added AgentNode instance examples, Jinja template bootstrapping, directory node coordination
- Section 7 (LSP Integration) - Replaced ASTAgentNode with AgentNode, added concrete code_lens/hover/code_action handler snippets
- Section 8 (Future) - Replaced RouteCSTNode subclass with data-driven FlaskRoute extension, enriched metadata flow
- Section 1.5 (Reactive Loop) - Fixed steps 5-10 to reference AgentNode, from_row(), to_system_prompt(), extra_tools
- Section 3 (Project Structure tree) - Removed agents/ JSONL directory, updated .remora/ tree
- TOC - Added 1.7 link

ALL SECTIONS COMPLETE. Ready to commit.

## Additional examples requested by user
- **File nodes** - file-level agents (e.g., __init__.py agent, README.md agent)
- **Directory nodes** - directory-level agents that manage structure
- **Jinja template bootstrapping** - nodes that can populate jinja templates to scaffold projects
- Mix these into existing examples throughout the doc

## Sections remaining to modify

1. **Section 1.4 (Discovery)**: Add paragraph about CSTNode -> projection -> AgentNode
   - Mention file nodes and directory nodes here
2. **Section 3 (Developer)**: Rewrite "Writing Extension Nodes" with data-driven examples
   - Test function agent (matches test_*, adds run_test tool)
   - API route agent (matches decorated functions, adds endpoint tools)
   - Config table agent (matches TOML tables, adds validation tools)
   - Monitor agent (meta-agent watching kernel events)
   - **File node agent** (matches file-level nodes, e.g., __init__.py gets export management)
   - **Template scaffolding agent** (file nodes that populate jinja templates)
   - **Directory node agent** (manages directory structure/organization)
3. **Section 4 (Agent)**: Update identity pipeline, show to_system_prompt()
4. **Section 5 (Node)**: Rewrite lifecycle with AgentNode at each stage
5. **Section 6 (Environment)**: Show AgentNode instances for different agents in chain
   - Add jinja template example to the library-spawning scenario
   - Show directory node coordinating file creation
6. **Section 7 (LSP)**: Show concrete AgentNode -> LSP conversion code
7. **Section 8 (Future)**: Replace subclass approach with data-driven extensibility

## Key AgentNode fields (for reference)
- node_id, node_type, name, full_name, file_path, start_line, end_line
- source_code, source_hash
- parent_id, caller_ids, callee_ids
- status, last_trigger_event, last_completed_at
- extension_name, custom_system_prompt, mounted_workspaces, extra_tools, extra_subscriptions

## Extension config pattern
```python
class SomeExtension(AgentExtension):
    @staticmethod
    def matches(node_type: str, name: str) -> bool: ...
    @staticmethod
    def get_extension_data() -> dict: ...  # returns field overrides
```
