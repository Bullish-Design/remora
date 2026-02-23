# AST SUMMARY MVP: Recursive Documentation & Review Concept

## 1. Goal of the MVP Demo
Create a demonstration script (`scripts/ast_summary_demo.py`) that operates as a recursive code reviewer and documentation engine. The goal is to prove the scalability and execution of the AST momentum model across multiple languages without the complexity of bidirectional code modifications (AST patching) for now.

The script will:
1. Parse a file (Python, Markdown, or TOML) using **Tree-sitter** to extract structured hierarchical nodes.
2. Generate nested **Cairn workspaces** corresponding to the hierarchical AST bounds.
3. Spawn an **LLM Agent** in each workspace to analyze only its specific AST code snippet and generate a markdown summary.
4. Recursively **"roll up"** these summaries: child nodes (methods) summarize themselves, and then parent nodes (classes) formulate their summaries incorporating their own logic *plus* the summaries of their children.

## 2. The Core Mechanics

### Phase 1: Tree-sitter Hierarchical Parsing
To build the recursive structure, we parse the source file and maintain parent-child relationships according to the file type:
1. **Python (`tree_sitter_python`)**: Extract the `Module` (root), `ClassDef`s, and `FunctionDef`s (methods and top-level functions).
2. **Markdown (`tree_sitter_markdown`)**: Extract the `Document` (root), sections (based on ATX headings `h1`, `h2`, etc.), and paragraph blocks.
3. **TOML (`tree_sitter_toml`)**: Extract the `Document` (root) and `table` / `table_array` blocks.
4. Build the universal `AstNode` tree:
   ```python
   class AstNode(BaseModel):
       node_type: str                  # e.g., "class_definition", "function_definition"
       name: str                       # e.g., "Coordinator", "process_node"
       source_text: str                # The *raw text* of just this node
       children: list['AstNode'] = []
       summary: Optional[str] = None   # Filled dynamically
   ```

### Phase 2: Recursive Cairn Workspace Provisioning
Once the AST Tree is built, we execute a recursive, concurrent async function.
1. For every node, spin up a `WorkspaceCache` context (e.g., `managed_workspace`).
2. Inside the Cairn workspace, create a `node_source.<ext>` file (e.g., `.py`, `.md`, `.toml`) containing only that node's `source_text`.
3. If the node has children, it asynchronously `await asyncio.gather(...)` for its children to run this exact same process first.

### Phase 3: LLM Summary Generation (Bottom-Up)
Generation happens strictly bottom-up. Leaf nodes activate first.
1. A leaf node (e.g., a simple utility function with no nested functions) provisions its sandbox.
2. It calls the LLM with the prompt: *"You are an AST Agent analyzing a `{node.node_type}` named `{node.name}`. Here is the code. Write a concise 1-sentence summary of what this node does. Output only markdown."*
3. The LLM result is saved to a `summary.md` inside its sandbox *and* attached to the in-memory `AstNode.summary`.
4. The child process completes.

### Phase 4: Recursive Roll-up (Aggregation)
The parent node (e.g., a `ClassDef`), having awaited its children, now has access to their generated summaries.
1. The parent provisions its sandbox.
2. It brings in its own `source_text`.
3. It calls the LLM with the prompt: *"You are a `{node.node_type}` named `{node.name}`. Here is your code. Importantly, here are the summaries of your sub-components [Inject Child Summaries]. Considering your code and your children's roles, write a cohesive paragraph summarizing the class's purpose and primary capabilities."*
4. The parent generates its `summary.md` and attaches it to its `AstNode.summary`.
5. This roles up until the root node (e.g., `Module` or `Document`) generates the final comprehensive file documentation.

## 3. Why This MVP Excels
1. **Flawlessly Demonstrates the AST Concept:** It proves that Remora can treat individual Tree-sitter nodes across multiple formats as isolated autonomous actors.
2. **Proves Cairn Sandbox Concurrency:** Demonstrates thousands of Cairn workspaces spinning up nested layers and tearing down cleanly in parallel.
3. **No Patching Risk:** Because the agents are generating standalone markdown rather than modifying the original file, we completely bypass the complex logic of reverse-byte AST patching and syntactic validation for the first MVP.
4. **Immediate Real-World Value:** The output of this script is actually incredibly valuable—it acts as an instantaneous, highly accurate architectural documentation generator that deeply understands code because the documentation is built bottom-up by specialized agents.
