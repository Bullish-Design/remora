# AgentNode: First-Class Swarm Agents

To make building and visualizing the swarm Pythonic, intuitive, and highly robust, we must elevate the concept of an "Agent" from a raw dictionary in `workspace.db` to a first-class, strictly typed object.

Below is a conceptual dive into the `AgentNode` pattern using `Pydantic`, Jinja2 for prompt rendering, and Grail for tool execution.

---

## 1. The Pydantic-Jinja Hybrid

Instead of manually constructing nested dictionaries for the LLM runner, developers should subclass a base `AgentNode`. 

**The core tenets:**
- **Class Docstring = The System Prompt.** It uses Jinja2 syntax natively.
- **Pydantic Fields = State/Template Variables.** The fields on the model are passed directly into the Jinja template rendering. This guarantees type safety for prompts.
- **Class Methods = Agent Tools.** The docstring of the method becomes the OpenAI tool description. The method body strictly delegates to the underlying Grail cluster.

### A Conceptual Example

```python
from pydantic import Field
from remora.agents import AgentNode, GrailTool

class CodeReviewerNode(AgentNode):
    """
    You are an expert Python code reviewer focusing on {{ project_name }}.
    Your goal is to evaluate the file at {{ file_path }} against strict PEP-8 standards.
    
    If you find an issue, use your `report_finding` tool immediately. 
    You have reviewed {{ files_reviewed }} files so far in this session.
    """
    
    project_name: str = "Remora Swarm"
    file_path: str
    files_reviewed: int = 0
    
    @GrailTool
    async def report_finding(self, line_number: int, issue_description: str, severity: str) -> str:
        """
        Report a code quality issue found during your review.
        
        Args:
            line_number: The exact line where the issue starts.
            issue_description: A concise description of the PEP-8 violation.
            severity: Must be one of 'low', 'medium', or 'high'.
        """
        return await self.grail.call(
            "linter_cluster.submit_finding", 
            file=self.file_path, 
            line=line_number, 
            issue=issue_description,
            severity=severity
        )
```

---

## 2. Treesitter Objects as First-Class AgentNodes

If we want *every* Treesitter object (class, function, method) to truly be its own agent, we need a dynamic instantiation factory. We can't ask users to manually write a Python `AgentNode` class for every single function in their codebase.

The solution is a **Polymorphic Agent Factory** combined with our **Persistent Node IDs**.

### Idea A: The Dynamic `ASTAgentNode`
We define a generic `ASTAgentNode` that sits on top of a Treesitter node. The Pydantic model holds the *code itself* as state.

```python
from typing import Literal
from pydantic import Field
from remora.agents import AgentNode, GrailTool

class ASTAgentNode(AgentNode):
    """
    You are an autonomous AI agent embodying the following Python {{ node_type }}:
    `{{ node_name }}`
    
    Your source code is:
    ```python
    {{ source_code }}
    ```
    
    Your Node ID is {{ remora_id }}. You are located in {{ file_path }}.
    You can only edit your own body. If you need to edit other functions, 
    you must message them or ask your parent class/file agent.
    
    Current incoming messages:
    {{ inbox_summary }}
    """
    
    node_type: Literal["function", "class", "method"]
    node_name: str
    source_code: str
    remora_id: str  # The unique hashtag parsed from the comment
    file_path: str
    
    @GrailTool
    async def rewrite_self(self, new_source_code: str, reason: str):
        """
        Rewrite your own underlying source code.
        Use this tool when you have decided a refactor or bugfix is necessary.
        """
        return await self.grail.call(
            "ast_editor.replace_node",
            file=self.file_path,
            node_id=self.remora_id,
            new_code=new_source_code
        )

    @GrailTool
    async def message_node(self, target_id: str, request: str):
        """Send a message to another specific Node ID in the swarm."""
        return await self.swarm.emit(
            to_agent=target_id,
            message=request
        )
```

### Idea B: The "Hydration" Factory
When Remora parses a file containing these IDs:
```python
# remora-id: hash892
def calculate_tax(amount):
    return amount * 1.2
```
Remora's AST parser dynamically "hydrates" an `ASTAgentNode` on the fly:

```python
node = parser.find_node_by_id("hash892")

# Instantiate the AgentNode Without Manual Parent Wiring
agent = ASTAgentNode(
    node_type=node.type,           # "function"
    node_name=node.name,           # "calculate_tax"
    source_code=node.text,
    remora_id=node.metadata["id"], # "hash892"
    file_path=node.filepath
)

# You now have a fully typed Python object representing that specific function in the swarm!
```

---

## 3. The Swarm Graph (Decoupling Agents from Topology)

You noted that configuring `parent_id` directly inside the Pydantic instantiation is clunky and rigid. 
The solution is to **completely decouple the Agent's Node from the Swarm's Edges.**

The Swarm Graph should be an independent, background process (or distinct service) that observes the codebase and maintains the topology, rather than forcing the agents to know their own hierarchy at instantiation.

### The "SwarmGraph" Process
Imagine a separate lightweight daemon (or an async task inside the main runner) called the `TopologyMapper`.

1. **Continuous AST Parsing:** It runs a fast Treesitter pass over the project whenever a file saves.
2. **Edge Discovery:** It looks at the `# remora-id: ...` anchors and maps out relationships:
   - *Containment Edges:* Function `abc_123` is inside Class `xyz_789`.
   - *Call Edges:* Function `abc_123` calls Function `def_456`.
3. **Graph Storage:** It syncs this topology directly into an external graph database, NetworkX instance, or a specialized `topology` table in SQLite.

### How this frees up the AgentNode:
Because the graph exists outside the agent, the AgentNode no longer needs a `parent_id` field. Instead, it interacts with the Swarm Graph via standard tools.

```python
class ASTAgentNode(AgentNode):
    # ... previous fields ...
    
    @GrailTool
    async def ask_parent(self, request: str):
        """Ask the node that contains you for help."""
        # The agent doesn't know who its parent is! 
        # Grail queries the independent Swarm Graph process to find out.
        parent_id = await self.grail.call("graph.get_parent", node_id=self.remora_id)
        return await self.swarm.emit(to_agent=parent_id, message=request)

    @GrailTool
    async def broadcast_to_callers(self, alert_message: str):
        """Warn any function that depends on you that your behavior changed."""
        caller_ids = await self.grail.call("graph.get_incoming_calls", node_id=self.remora_id)
        for c_id in caller_ids:
            await self.swarm.emit(to_agent=c_id, message=alert_message)
        return f"Alerted {len(caller_ids)} dependent nodes."
```

### The "Dual Process" Architecture
This sets up a beautiful separation of concerns:
- **Process 1: The SwarmGraph Daemon.** A fast, low-compute process that watches files, runs Treesitter, and maintains a strict map of Node IDs (`A` is inside `B`, `A` calls `C`).
- **Process 2: The SwarmExecutor.** The LLM runner that spawns `AgentNode` Pydantic objects on demand. When an agent wakes up, it queries the SwarmGraph to understand its surroundings, rather than having its surroundings hardcoded into its instantiation.

This makes the system incredibly resilient. You can drag and drop a function to a different file, the SwarmGraph daemon instantly redraws the edges in the background, and the AgentNode (which kept its persistent ID) just wakes up in its new home, completely unbothered.
