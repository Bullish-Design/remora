# AST MOMENTUM MVP: Implementation Ideation

This document outlines the fastest, most effective path to building a demonstrable Minimum Viable Product (MVP) of the AST_MOMENTUM concept within the Remora ecosystem.

## 1. Goal of the MVP
The core goal is to demonstrate **one root node automatically generating and validating its child nodes concurrently** using Remora's existing tools (Cairn sandboxes, Tree-sitter discovery, and `pym` scripts).

**Target Use Case:** A `pyproject.toml` file generator.
*Why `pyproject.toml`?* 
- It's highly structured (TOML tables are clear AST nodes).
- It naturally splits into distinct, non-overlapping domains (e.g., `[project]`, `[tool.pytest]`, `[tool.ruff]`).
- It avoids the immediate complexity of resolving Python imports or complex cross-file syntax trees while still demonstrating the core value.

---

## 2. What We Have vs. What We Need

### What Remora Already Has:
1. **Tree-Sitter / Pydantree Integration**: Ability to parse code into a typed AST and run queries.
2. **Cairn Workspace Bridge**: The ability to spin up isolated `.cache/remora/workspaces/` environments, run commands (like a linter or test), and merge them back to the parent without conflicts.
3. **Structured Agents & `.pym` Scripts**: The execution engine to pass context to an LLM and parse the result.
4. **Coordinator**: An `asyncio`-based orchestrator capable of managing concurrent tasks (`process_node`).

### What We Are Missing (The MVP Delta):
1. **AST Agent Base Models**: We need a Pydantic model that represents an "Agentic Node" (e.g., `AstAgent`). This model must know its AST start/end byte ranges and hold references to its parent and children.
2. **The "Broadcast Bus" (Intent Router)**: The existing Coordinator maps operations to *files* via config. In AST_MOMENTUM, the parent node needs a way to receive a user intent (e.g., "Add pytest-cov") and broadcast it to its child agents, asking them: *"Is this relevant to your domain?"*
3. **Template Bootstrapping**: A mechanism to say, *"I am creating a pyproject.toml FileAgent. Based on my `templateer` config, I must immediately spawn a `ProjectBlockAgent` and a `ToolBlockAgent`."*
4. **Sub-node Merging Logic**: Right now, Cairn merges a whole workspace back to a project root. We need the ability for a generic Cairn merge to overwrite *only* the specific byte-range/AST node of the parent file.

---

## 3. Step-by-Step MVP Implementation Plan

To get to a working demo as fast as possible, we should build a standalone script or a focused test-case within Remora (e.g., `scripts/ast_momentum_demo.py`) rather than immediately attempting a massive refactor of the `Coordinator`.

### Phase 1: The `AstAgent` Data Structure
Create a lightweight Pydantic hierarchy representing the "living" file.

```python
class AstAgent(BaseModel):
    node_type: str                  # e.g., "file", "table"
    byte_range: tuple[int, int]     # Where this agent's jurisdiction begins and ends
    parent: Optional['AstAgent']    
    children: list['AstAgent'] = []
    sandbox_id: Optional[str] = None # The Cairn workspace ID
    grail_script_path: Path         # The specialized prompt/rules for this agent
```

### Phase 2: The TOML `Templateer` Spec
Define a rigid skeleton for our target file. We don't need the full `templateer` library integrated yet—just a hardcoded dictionary simulating it for the MVP.
- Root: `pyproject.toml`
  - Child 1: `[project]` table (managed by `project_agent.pym`)
  - Child 2: `[tool.pytest.ini_options]` table (managed by `pytest_agent.pym`)

### Phase 3: The Relevance Evaluator (The Gatekeeper)
Implement a simple LLM call (or even regex for the MVP) where a child agent evaluates a user prompt.
```python
async def evaluate_intent(agent: AstAgent, user_prompt: str) -> bool:
    # MVP: Hardcoded or simple LLM binary yes/no based on agent's grail_script description.
    pass
```

### Phase 4: Concurrent Sandbox Generation
When the root `pyproject.toml` agent is triggered:
1. It initializes its root Cairn sandbox.
2. It spawns its two children.
3. Each child evaluates the user prompt (e.g., *"Make a basic project with pytest"*).
4. Both children realize they need to act.
5. They concurrently spin up their own Cairn sandboxes via the existing `WorkspaceManager`.
6. They execute their specific `.pym` scripts to generate their TOML strings and write them to a temporary file in their sandbox.
7. They validate their own TOML (e.g., by running `python -c "import tomllib..."` inside their sandbox).

### Phase 5: The "Jujutsu" Stitch (AST Patching)
The trickiest part of the MVP. Instead of a standard Git-style file merge, the parent agent needs to stitch the strings together based on AST blocks.
- **Simplest MVP Approach**: Because we are generating a file from scratch (or adding distinct blocks), the parent agent simply concatenates the validated strings returned by the children in the order defined by the template. 
- **Future State**: The child returns a `(byte_start, byte_end, new_string)` patch, and the parent applies the text patch and re-runs Tree-sitter to ensure the global AST hasn't corrupted.

---

## 4. Why This MVP Works
- **Fast to Build**: We skip rewriting Remora's core `Coordinator` and just write a demo script using Remora's internal tools (`WorkspaceManager`, `KernelRunner`).
- **Proves the Core Thesis**: It demonstrates concurrent, context-bounded generation that evaluates its own syntax before merging.
- **Extensible**: Once the `pyproject.toml` TOML stitcher works, we can upgrade the stitching logic to handle Python AST nodes (Class/Method generation) using `pydantree`.
