# AST_MOMENTUM: Recursive Node Generation

## The Core Concept
Shift Remora from a post-hoc analysis and enhancement tool into a **proactive velocity engine** where Tree-sitter nodes act as recursive, self-generating sub-agents. 

In the AST_MOMENTUM paradigm, code is not generated top-down as one massive string of text. Instead, generation mirrors the AST structure: root nodes spawn structural child nodes, which in turn spawn leaf nodes. Every grammatical block in the project is an intelligent entity that knows exactly how to build, maintain, and gatekeep its own subset of the code.

### 1. Nodes as Generative Agents
Every Tree-sitter node (e.g., a File, a Class definition, a TOML table) is instantiated as an agent. The node possesses:
- **Self-Awareness**: It knows its type, boundaries, and required schema.
- **Parental Context**: It understands its role in the overall file or project.
- **Generative Capability**: It knows which sub-nodes it must create to fulfill its purpose.

### 2. Scaffold Bootstrapping (`templateer` + `grail` `pym` scripts)
When a node is initialized, it does not immediately call an LLM blindly. It loads specialized local context and templates. 
- **`templateer`** provides the structural boilerplate (the "skeleton"). It tells a `pyproject.toml` node: *"You must have a project block, a testing block, a scripts block, and a tools block."*
- **`grail`** `.pym` scripts provide the targeted generation logic (the "muscle"). It gives sub-nodes the explicit prompts, tools, and constraints to write their specific implementation.

### 3. Recursive Delegation & Concurrency
Because the AST inherently isolates components, nodes can spawn and generate concurrently. 
If a `Class` node realizes it needs 5 methods based on its template context, it spawns 5 `Method` agents. These 5 agents generate their code simultaneously because their AST boundaries do not conflict. This creates massive **momentum** and unprecedented generation speed.

## Full Remora Integration: The Cairn Sandbox

AST_MOMENTUM doesn't just generate text; it verifies and tests *in situ*. This is where Remora's core capability—the **Cairn Workspace Bridge**—becomes the engine of validation.

### Isolated Child Sandboxes
Every AST Agent, when spawned, is provisioned its own isolated Cairn Sandbox.
- **The Concept**: When a `MethodAgent` is tasked with writing `def calculate_total(self)`, it doesn't just string words together. It writes the code into its ephemeral Cairn Sandbox.
- **Self-Verification**: The `MethodAgent` uses its `grail` script to execute targeted linting (Ruff), type-checking (Pyright), or even localized unit tests within that sandbox. 
- **The Result**: The agent only marks its task as "complete" when its sandbox environment passes all validation checks. It returns a *proven* AST node to its parent, not an untrusted string.

### Parent-Child Sandbox Merging (The "Jujutsu")
Because AST nodes are inherently hierarchical, their sandboxes must be composable.
- When a child `MethodAgent` completes its work, it "commits" its sandbox changes to the parent `ClassAgent`'s sandbox.
- **The Merge Conflict Free Zone**: Because each child was strictly constrained to its specific Tree-sitter byte range, merging sandboxes is largely a non-conflicting overlay operation. The `ClassAgent` accepts the patches from its various `MethodAgents`.
- **Higher-Level Validation**: The `ClassAgent` now has a populated sandbox containing all its new methods. It runs *class-level* validation (e.g., checking that all methods correctly implement an interface, running class-scoped tests). 
- **Upward Propagation**: This process continues up the chain. The `ClassAgent` commits to the `FileAgent`'s sandbox, which commits to the `ModuleAgent`'s sandbox. The final result presented to the user at the repo level is fully tested, fully typed, and structurally sound code.

### 4. Gatekeeping & Bounded Contexts
When a user wants to make a change, the request is broadcasted hierarchically.
Instead of a single heavy LLM deciding which lines of text to edit, the request filters down the AST.

**Example: Modifying `pyproject.toml`**
1. **User Request**: *"Add a dependency for requests and set up pytest-cov in the standard config."*
2. **File Agent (`pyproject.toml`)**: Broadcasts the intent to its sub-agents.
3. **Sub-Agents Evaluate**:
   - `ScriptsBlockAgent`: *"No scripts mentioned. That's not my job."*
   - `ToolsBlockAgent`: *"No tool configuration changes (like Ruff or Black) requested. I'll pass."*
   - `ProjectBlockAgent`: *"I handle dependencies. Adding `requests` to `dependencies` list. I'm on it."*
   - `TestBlockAgent`: *"I handle test configurations. Setting up `pytest-cov`. Sure, starting on that now, I'll let you know when it's verified."*
4. **Execution and Verification**:
   - The `ProjectBlockAgent` and `TestBlockAgent` each spin up their Cairn Sandboxes, make the modifications, and run any required `.pym` validation checks (e.g., running `uv pip sync` in the sandbox to ensure the new dependency resolves).
   - Once validated, they commit their changes back to the `pyproject.toml` File Agent's sandbox.

This distributed gatekeeping drastically reduces prompt size per agent, reduces hallucinations (agents only see their local chunk of the AST), and prevents agents from accidentally breaking code outside their purview.

## Technical Architecture Thoughts

- **Pydantic-Backed Nodes**: Nodes inherit from a base `AstAgent(BaseModel)`. This model tracks tree-sitter byte ranges, children, parent references, and the ID of its active Cairn Sandbox.
- **Byte-Range Sandboxing & Merging**: Sub-agents only have write permissions to their specific byte range in the file. Alternatively, leaf nodes return AST/text "patches" that the parent securely applies and validates in its own sandbox environment, utilizing an efficient layered file system approach.
- **Rejection & Healing**: If a `MethodAgent` generates syntactically invalid code or fails its sandbox tests, it self-heals by analyzing the runtime error. If it cannot resolve it, the parent `ClassAgent` can reset the child's sandbox and provide updated context based on the failure.
- **Vast Scalability**: AST_MOMENTUM scales from single files to entire repositories. A `RepoAgent` manages `DirectoryAgents`, which manage `FileAgents`, which manage `ClassAgents`, down to `ExpressionAgents`. Every layer provides a safety net of Cairn-backed validation. 

## Path to MVP
1. **Identify the AST Root Layer**: Start with a simple file generator (like `pyproject.toml` or `README.md`) using `templateer` to define the blocks.
2. **Implement the Broadcast Bus**: Build the mechanism where a parent sends an intent to its children, and the children vote on whether to process it (`evaluate_relevance(intent) -> float`).
3. **Wire Grail Scripts**: Give each child block a focused `.pym` script.
4. **Un-parse & Stitch**: Implement the mechanism that takes the generated content of all child agents and flawlessly stitches it back into a valid document.
