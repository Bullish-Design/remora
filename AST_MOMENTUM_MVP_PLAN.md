# AST MOMENTUM MVP: Detailed Implementation Plan

## 1. Goal of the MVP Demo
Create a standalone demonstration script (`scripts/ast_momentum_demo.py`) that updates an **existing** `pyproject.toml` file based on a natural language user intent. The script will prove the core AST Momentum concepts by:
1. Using **Tree-sitter** to parse the file into autonomous AST node agents.
2. Routing the intent only to relevant sub-nodes.
3. Using **Cairn workspaces** to concurrently execute and validate the changes in isolation.
4. Using byte-range replacement ("AST Patching") to stitch the file back together without merge conflicts.

## 2. The Demo Scenario
- **Input File:** An existing `pyproject.toml`.
- **User Intent:** `"Add requests as a dependency and configure pytest-cov with 80% coverage threshold."`
- **Expected Outcome:** The `[project]` table is updated with the new dependency, and the `[tool.pytest.ini_options]` table is created or updated concurrently. The final file remains syntactically valid and non-corrupted.

## 3. Step-by-Step Implementation Detail

### Phase 1: Tree-sitter AST Parsing & Agent Instantiation
Instead of operating on strings, the file is parsed into structural components.
1. Use Remora's `SourceParser("tree_sitter_toml")` to parse the `pyproject.toml` file.
2. Define the `AstAgent` Pydantic model to hold the context:
   ```python
   class AstAgent(BaseModel):
       node_type: str                  # e.g., "document", "table"
       name: str                       # e.g., "root", "project", "tool.pytest"
       byte_range: tuple[int, int]
       source_text: str
       children: list['AstAgent'] = []
   ```
3. Write a Tree-sitter query to extract top-level tables (`[project]`, `[build-system]`, `[tool.*]`).
4. Instantiate the root `AstAgent` (document) and child `AstAgent`s (tables). Unrecognized or irrelevant nodes (like whitespace between tables) can be ignored for patching if we only replace specific table ranges.

### Phase 2: Intent Routing (The Broadcast Bus)
The parent agent must decide which children should handle the user's request.
1. Implement an async `evaluate_relevance(intent: str, agent: AstAgent) -> bool` function.
2. This function makes a fast LLM call (e.g., using Remora's structured-agents wrappers):
   *"Given the user intent '{intent}' and your TOML table '{agent.name}', do you need to modify your contents? Return true or false."*
3. Execute this evaluation concurrently across all child `AstAgent`s.
4. Filter down to only the agents that return `True` (e.g., the `project` agent and `tool.pytest` agent).

### Phase 3: Concurrent Cairn Workspace Execution
For each relevant child agent, we must create a safe environment to generate and test its code.
1. Use `cairn.runtime.workspace_cache.WorkspaceCache` or Remora's `managed_workspace` utility to spin up an isolated temporary directory for each active agent concurrently.
2. Inside the sandbox, create a temporary file containing *only* the agent's specific source text (e.g., just the `[project]` table text).
3. Execute a generator script (simulating a `.pym` grail script):
   - Pass the user intent and the node's source text to an LLM.
   - Instruct the LLM to return the updated TOML code for that specific block.
4. **Self-Validation:** Still inside the Cairn sandbox, run a validation step on the output before accepting it. For the MVP, calling `tomllib.loads(generated_text)` or running `tree_sitter_toml` on the isolated snippet ensures no syntax errors were introduced. 
5. If validation fails, the agent can retry or mark itself as errored. If successful, it returns the `(start_byte, end_byte, new_text)` patch.

### Phase 4: The "Jujutsu" Stitch (AST Patching)
The root agent collects the successful patches from all concurrent child operations and merges them into the original file.
1. Sort the received patches by their `start_byte` in **descending** (reverse) order.
2. Why reverse? Modifying a file from bottom-to-top ensures that changing the length of a node at the bottom does not shift the byte offsets of the nodes above it.
3. Apply the patches:
   ```python
   final_bytes = bytearray(original_source_bytes)
   for patch in reversed_patches:
       final_bytes[patch.start_byte : patch.end_byte] = patch.new_text.encode('utf-8')
   ```
4. **Final Global Validation:** Parse the `final_bytes` with `SourceParser("tree_sitter_toml")`. If `tree.root_node.has_error` is false, the file is flawlessly stitched. Write it to disk.

## 4. Why This Approach Excels
- **No Hallucinations Outside Scope:** Because the `project` agent only receives the `[project]` bytes in its sandbox, it is physically impossible for it to accidentally delete the `[build-system]` table.
- **Speed:** The `[project]` agent and `[tool.pytest]` agent do their LLM calls, text generation, and syntax validation entirely in parallel.
- **Real-World Remora Integration:** This uses Remora's actual parsing libraries, async coordination patterns, and Cairn abstractions, proving viability for broader scaling to Python AST nodes (`ClassDef`, `FunctionDef`).
