# Remora Neovim V2: The Complete Concept

This document consolidates the architectural vision for the next iteration of the Remora Neovim integration. It merges several brainstorming sessions into a single, cohesive blueprint encompassing Swarm graph topology, Pydantic-driven AgentNodes, and LSP-native editing.

---

## 1. The Core Philosophy: "The Code is the Swarm Graph"

In V1, agents were abstract dictionary structures tied to fragile line numbers, leading to massive workspace bloat when files were edited.

In V2, we introduce **Persistent Node IDs**. 

Instead of deriving IDs dynamically, the background SwarmGraph daemon actively parses the AST and automatically injects an ID into the code at the exact line the node starts. To keep the code perfectly clean and readable, these IDs are right-aligned to exactly 150 characters (your preferred line width constraint) with no extra text prefix.

```python
def format_date(dt: datetime) -> str:                                                                                                     # abc_123
    """Format datetime for display."""
    pass
```

*(In Neovim, these 8-character comments can still be hidden via syntax `conceal` or styled to faintly blend into the background. Because they are on the same line as the `def` or `class` keyword, they don't shift line numbers downward.)*

Because this ID travels with the function block even if the user cuts and pastes it to a new file, the Agent mapping is entirely stable across sessions.

---

## 2. First-Class AgentNodes (The Python Implementation)

To maintain sanity and predictability when interacting with the vLLM server, there is exactly one *actual* underlying prompt structure sent to the LLM: **The Base `ASTAgentNode`**.

This "monster prompt" contains the universal instructions every Swarm Agent needs to function, ensuring consistent routing, output formatting, and context awareness.

### 2a. The Foundation: The Base `ASTAgentNode`

The absolute base structure sent to vLLM looks like this. It is a massive, strictly typed Pydantic class:

```python
from typing import Literal
from pydantic import BaseModel, Field

class ASTAgentNode(BaseModel):
    """
    You are an autonomous AI Agent embodying the following Python {{ node_type }}:
    `{{ node_name }}`
    
    # Context
    Your Node ID is `{{ remora_id }}`. You are located in `{{ file_path }}`.
    Your underlying source code is:
    ```python
    {{ source_code }}
    ```
    
    # Swarm Graph Awareness
    Your parent node is: {{ parent_id }}
    You are called by these nodes: {{ caller_nodes }}
    
    # Custom Instructions / Personality
    {{ custom_system_prompt }}
    
    # Active Workspaces / Mounted Data
    {{ mounted_workspaces }}
    
    # Directives
    You can only edit your own body using your AST manipulation tools. 
    If you need to edit other functions, you must message their Node IDs or ask your parent.
    """
    
    node_type: Literal["function", "class", "method", "file"]
    node_name: str
    source_code: str
    remora_id: str
    file_path: str
    parent_id: str | None = None
    caller_nodes: list[str] = Field(default_factory=list)
    
    # These fields are injected dynamically by subclasses!
    custom_system_prompt: str = ""
    mounted_workspaces: str = "None"

    # Base Tools available to ALL nodes
    @GrailTool
    async def rewrite_self(self, new_source_code: str): ...
    
    @GrailTool
    async def message_node(self, target_id: str, request: str): ...
```

### 2b. The Subclasses: Custom Brain Injections

A user wants to create a `ConfigNegotiator` agent. Instead of reinventing the entire prompt loop, the user subclasses the system to **inject** specific behavior into the Base Node. 

The custom subclass is "swallowed up" by the Base Node during instantiation.

```python
from remora.agents import ExtensionNode, GrailTool

class ConfigNegotiator(ExtensionNode):
    # Pattern matching for auto-discovery
    match_type = "class"
    match_name = "Config*"
    
    # Injected into the `{{ custom_system_prompt }}` block
    system_prompt = "You handle all environment variables. Negotiate strictly on standard constants."
    
    # Injected into the `{{ mounted_workspaces }}` block
    def get_workspaces(self) -> str:
        return "- /etc/secrets/ (read-only)\n- .env.template (read-write)"

    # These tools are dynamically appended to the Base Node's tools before sending to vLLM
    @GrailTool
    async def read_env_file(self, filepath: str):
        """Read a configuration file specifically."""
        return await self.grail.call("fs.read", path=filepath)
```

**Why this is genius:**
- vLLM only ever sees one consistent, highly-optimized System Prompt structure.
- The Swarm Runner only has to deal with one core Agent Model (`ASTAgentNode`).
- The user's custom class acts purely as a structured **payload** (adding specific Tools, text, and data access limits) that docks into the main Agent.

### 2c. Auto-Discovery via `.models/`

To prevent the user from writing explicit registration code (`swarm_config.py` is dead!), we use a pure **File-System Auto-Discovery** approach.

The user drops their custom Pydantic Python files into a specific directory:
```
my_project/
  .remora/
    .models/
      logger_agents.py
      config_agents.py
```

When the Remora Daemon boots, it iterates over all Python files strictly in `.remora/.models/`. It dynamically imports them and registers any class descending from `ExtensionNode`. 

**The Full Hydration Flow:**
1. Background SwarmGraph sees a new class named `ConfigLoader`. It ensures `# abc_123` is right-aligned on the class definition.
2. The AgentRunner needs to wake up `abc_123`.
3. It constructs the Base `ASTAgentNode`.
4. It checks the `.models/` registry. It sees `ConfigNegotiator` matches the name `ConfigLoader`.
5. It swallows `ConfigNegotiator`, injecting its `system_prompt`, its `read_env_file` tool, and its workspace data into the master Base Node.
6. The fully assembled Base Node is sent to vLLM. 

This requires zero configuration from the developer other than writing clean OOP Python in a specific folder.

---

## 3. Decoupling Topology: The Dual-Process Architecture (Rustworkx + SQLite)

In V1, the Swarm state attempted to hold both Agent status and Swarm hierarchy. This proved rigid. In V2, we separate the Agent from the Graph entirely and introduce extreme performance using **Rustworkx** backed by **SQLite**.

### 3a. Process 1: The SwarmGraph Daemon (The Mapper)
A fast, lightweight AST watcher runs continuously in the background. It doesn't hold the graph in memory; its only job is to update a durable `sqlite3` table (`node_topology`).
- When a file saves, it sweeps the `# remora-id: ...` anchors.
- It writes edges (`parent_of`, `calls_to`) strictly to the SQLite database.

### 3b. Process 2: The AgentRunner (The Worker)
When the LLM triggers an AgentNode, we need to understand its surroundings instantly. Doing heavy SQL JOIN queries for tree traversal is too slow.

Instead, the AgentRunner utilizes a **Lazy Rustworkx Graph** (`rustworkx.PyDiGraph`).
1. **The Wakeup:** An agent wakes up representing Node `A`.
2. **Lazy Hydration:** If Node `A` isn't in the Rustworkx memory space yet, the Runner makes a single fast query to SQLite: *"Give me Node A and a depth-2 neighborhood of edges."*
3. **Rustworkx Caching:** It inserts those nodes and edges into the `rustworkx.PyDiGraph`.
4. **Lightning Execution:** The agent can now use Grail tools like `get_descendants()` or `find_shortest_call_path()`. These Tools execute directly against the C-optimized Rustworkx memory struct in micro-seconds.

```python
    @GrailTool
    async def ask_parent(self, request: str):
        """Ask the node that contains you for help."""
        # 1. Checks Rustworkx graph in-memory. 
        # 2. If missing, pulls edges from SQLite and caches them in Rustworkx.
        # 3. Performs traversal instantly.
        parent_id = await self.grail.call("graph.get_parent", node_id=self.remora_id)
        return await self.swarm.emit(to_agent=parent_id, message=request)
```

**The result:** You get the absolute best of both worlds. The topology is safely and durably persisted to SQLite (surviving system crashes), but the Agents traverse heavily connected graph topology using extreme-performance Rust algorithms, operating entirely via lazy, on-demand rehydration.

---

## 4. The Editor Integration: "No-Type" UI Control

To achieve a truly cohesive system, the developer shouldn't have to bounce between writing python code and pushing UI buttons. **The goal is a "No-Type" interface:** the user strictly interacts with the UI, and the agents write all the code.

By combining the Language Server Protocol (LSP) and the reactive `nui-components.nvim` library, the UI becomes a dynamic control panel for the AST.

### 4a. Dynamic Action Forms (UI from Pydantic)
Because our `ExtensionNode` subclasses are strictly typed Pydantic models (and their tools have typed arguments), the UI handles them automatically.
- When Neovim hovers over an AgentNode, an RPC call fetches that Agent's tools.
- `nui-components` parses the tool schemas and **auto-generates UI Forms**.
- If a `ConfigNegotiator` has a tool `read_env_file(filepath: str, create_if_missing: bool)`, the sidebar instantly renders a text box for `filepath`, a toggle for `create_if_missing`, and an `[Execute]` button.
- **The developer never writes code to use tools.** They fill out UI forms that speak directly to the underlying Pydantic methods.

### 4b. "Ghost Nodes" for UI-Driven Creation
How do you create a new Python function without typing it?
1. The user goes to an empty line in the editor and presses a hotkey (e.g., `<leader>cn` for Create Node).
2. The LSP instantly inserts a "Ghost Node"—a blank line with a permanent `# remora-id: ghost_888` right-aligned comment.
3. The `nui-components` sidebar pops open an "Instruction Prompt" form.
4. The user types: *"Create an async function that establishes a Postgres connection string."* and hits `[Submit]`.
5. The Swarm routes this prompt to a Coding Agent, anchoring it to `ghost_888`. The Agent generates the exact AST text, replaces the ghost node in the buffer via the LSP, and the `# ghost_888` ID transitions into a permanent Node ID. 

### 4c. Diff Approvals (Zero-Type Refactoring)
When an agent (like a background Linter or a commanded Coder) decides a node needs changing, it doesn't just blindly overwrite the buffer text.
- The Agent emits a `RewriteProposalEvent`.
- Neovim intercepts the SSE event. The `nui-components` border changes to Gold to alert the user.
- The user clicks the sidebar, which opens a **Syntax-Highlighted Diff View** (using Nui's buffer components) showing the Agent's proposed rewrite vs the current AST.
- The UI exposes two buttons: `[Accept]` and `[Reject (Chat)]`. 
- If accepted, the LSP applies the text edit. If rejected, it opens a chat form for the user to steer the Agent's next attempt.

### 4d. The Perfect Synergy
This model unifies the entire stack into a single concept:
- The **AST** maps directly to **Pydantic Classes**.
- The **Pydantic Classes** project their arguments directly into **Nui UI Forms**.
- The user fills the **UI Forms**, which triggers the **Agent**.
- The **Agent** proposes changes to the **AST**, completing the loop with zero manual python typing required from the human.

---

## Summary
V2 transforms Remora from a heavy, monolithic script into a 100% UI-driven ecosystem. 
1. **Right-Aligned 150-Col IDs** provide perfectly clean, stable persistent anchors.
2. **Base AST Nodes + `.models/`:** Custom agents are dropped into a folder. Their Pydantic schemas auto-map to the AST and auto-generate Nui-components UI Forms.
3. **Decoupled SwarmGraphs** allow code to physically move without breaking agent hierarchies.
4. **No-Type UI Control:** Through Ghost Nodes and UI Diff Approvals, the developer acts strictly as an orbital commander, letting the Swarm write all the actual code.
