# AST Summary: Junior Developer Implementation Guide

This guide provides a comprehensive, step-by-step roadmap for implementing the **AST Summary Engine** as a brand-new, standalone Python library.

The goal of this library is to parse a file (Python, Markdown, or TOML) into an AST (Abstract Syntax Tree), spin up concurrent isolated workspaces for each node, and use an LLM to generate summaries bottom-up (aggregating child summaries into parent summaries), all while emitting progress to a beautiful terminal dashboard.

---

## Step 1: Project Initialization & Architecture

First, initialize the library and install the powerful base dependencies.

```bash
mkdir ast-summary
cd ast-summary
uv init --lib

# Add core processing libraries
uv add pydantic tree-sitter tree-sitter-python tree-sitter-markdown tree-sitter-toml 

# Add UI and internal libraries
uv add rich textual cairn structured-agents grail
```

### Module Structure
Create the following file structure inside `src/ast_summary/`. This strict separation of concerns makes testing significantly easier.

```text
src/
└── ast_summary/
    ├── __init__.py
    ├── models.py        # Pydantic state models (AstNode)
    ├── parser.py        # Tree-sitter file parsing logic
    ├── engine.py        # Async Workspace & LLM generation logic
    ├── events.py        # Real-time event emitters
    ├── cli.py           # Typer/Argparse entry points
    └── tui.py           # Textual dashboard interface
```

---

## Step 2: The Data Models (`models.py`)

**Goal:** Create a standardized representation of a code block, regardless of the underlying language.

```python
# src/ast_summary/models.py
from typing import Optional
from pydantic import BaseModel, Field

class AstNode(BaseModel):
    """Represents a universal structural block of a file."""
    node_type: str                  # e.g., "Module", "ClassDef", "Table"
    name: str                       # e.g., "process_node" or "File Root"
    source_text: str                # Raw text of this specific block
    children: list['AstNode'] = Field(default_factory=list)
    summary: Optional[str] = None   
    status: str = "pending"         # Tracks progress for the UI
```

**Testing Strategy:** Unit test this file purely by creating mock `AstNode` hierarchies and verifying Pydantic serialization/validation works.

---

## Step 3: The Universal Parser (`parser.py`)

**Goal:** Take a file path, load the correct Tree-sitter grammar, and recursively extract meaningful boundaries into `AstNode` objects.

```python
# src/ast_summary/parser.py
from pathlib import Path
from tree_sitter import Language, Parser, Node
import tree_sitter_python
from ast_summary.models import AstNode

def parse_python_file(file_path: Path) -> AstNode:
    """Parse a python file into a hierarchical AstNode tree."""
    language = Language(tree_sitter_python.language())
    parser = Parser(language)
    
    source_bytes = file_path.read_bytes()
    tree = parser.parse(source_bytes)
    
    return _build_python_tree(tree.root_node, source_bytes)

def _build_python_tree(node: Node, source_bytes: bytes, parent: AstNode | None = None) -> AstNode | None:
    # 1. Handle the Root File
    if node.type == "module":
        ast_node = AstNode(
            node_type="Module", 
            name="File Root", 
            source_text=source_bytes[node.start_byte:node.end_byte].decode("utf-8")
        )
        for child in node.children:
            _build_python_tree(child, source_bytes, ast_node)
        return ast_node

    # 2. Extract Classes and Functions
    if node.type in ("class_definition", "function_definition"):
        # Helper to find the node's name
        name_node = next((c for c in node.children if c.type == "identifier"), None)
        name = source_bytes[name_node.start_byte:name_node.end_byte].decode("utf-8") if name_node else "anonymous"
        
        node_type = "ClassDef" if node.type == "class_definition" else "FunctionDef"
        ast_node = AstNode(
            node_type=node_type, 
            name=name, 
            source_text=source_bytes[node.start_byte:node.end_byte].decode("utf-8")
        )
        
        if parent is not None:
            parent.children.append(ast_node)

        # 3. Recurse into the block to find nested methods
        for child in node.children:
            if child.type == "block":
                for subchild in child.children:
                    _build_python_tree(subchild, source_bytes, ast_node)
        return ast_node
    return None
```

**Gotchas & Careful Considerations:**
- **Treesitter offsets are byte-based, not character-based.** Always use `.read_bytes()` and `.decode("utf-8")` when extracting text, never `.read_text()`.
- **Ignore Whitespace:** Tree-sitter includes comments and whitespace as nodes. If you aren't explicitly matching `class_definition` or `function_definition`, ignore it so the tree doesn't get flooded.

**Testing Strategy:** Create a dummy `test_file.py` with a Class and a nested Method. Assert that `parse_python_file` returns a root `Module` node with exactly 1 `ClassDef` child, which has exactly 1 `FunctionDef` child.

---

## Step 4: Event Emitting (`events.py`)

**Goal:** Create a simple decoupled way to broadcast what the engine is doing so the UI can draw it.

```python
# src/ast_summary/events.py
import json
import time
from pathlib import Path

EVENT_FILE = Path(".summary_events.jsonl")

def emit_event(event_type: str, node_name: str, message: str = "", **extra) -> None:
    """Emit an event for the dashboard to ingest."""
    payload = {
        "timestamp": time.time(),
        "event": event_type,
        "node": node_name,
        "message": message,
        **extra
    }
    with EVENT_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload) + "\n")
```

---

## Step 5: The Recursive Generation Engine (`engine.py`)

**Goal:** Process the `AstNode` tree **bottom-up**. We must wait for children to generate their summaries before we can generate the parent summary.

**Remora Integration Detail:** We use the `cairn` library's `WorkspaceManager` here. Every single node gets its own isolated `.db` sandbox to prevent any crosstalk or concurrent write issues while the LLM generates the summary.

```python
# src/ast_summary/engine.py
import asyncio
from pathlib import Path
from cairn.runtime.workspace_manager import WorkspaceManager
from ast_summary.models import AstNode
from ast_summary.events import emit_event

# Mock LLM generation for demonstration
async def generate_summary(node: AstNode, child_summaries: list[str]) -> str:
    await asyncio.sleep(1.5) # Simulate LLM thinking...
    
    if not child_summaries:
        return f"This {node.node_type} (`{node.name}`) performs specific logic."
    
    # If this is a parent node, roll up the children!
    rollup = "\n".join([f"- {s}" for s in child_summaries])
    return f"The {node.node_type} (`{node.name}`) manages:\n{rollup}"

async def process_node(node: AstNode, workspace_manager: WorkspaceManager, cache_root: Path) -> str:
    """Recursively process a node: spin up workspace, await children, summarize."""
    
    # 1. BOTTOM-UP RECURSION: Wait for all children to finish FIRST.
    child_tasks = [process_node(child, workspace_manager, cache_root) for child in node.children]
    child_summaries = await asyncio.gather(*child_tasks)

    # 2. PROVISION ISOLATED CAIRN WORKSPACE
    workspace_id = f"summary-{id(node)}"
    workspace_db = cache_root / "workspaces" / workspace_id / "workspace.db"
    workspace_db.parent.mkdir(parents=True, exist_ok=True)
    
    emit_event("provisioning", node.name, f"Booting Cairn workspace for {node.node_type}")
    
    # 3. EXECUTE GENERATION INSIDE WORKSPACE
    async with workspace_manager.open_workspace(workspace_db) as workspace:
        
        # Give the LLM only the text for this specific node
        await workspace.files.write("/node_source.txt", node.source_text)
        
        emit_event("generating", node.name, "Running LLM inference...")
        
        # In the future, this calls structured-agents AgentKernel
        summary = await generate_summary(node, child_summaries)
        
        # Save results
        node.summary = summary
        node.status = "done"
        await workspace.files.write("/summary.md", summary)
    
    emit_event("done", node.name, "Summary complete", summary=summary)
    return summary
```

**Gotchas & Careful Considerations:**
- **`asyncio.gather` is destructive if not handled carefully.** If one child task throws an exception, `gather` will bubble it up and cancel the others. We must implement generic `try/except` mapping inside `process_node` to ensure that a single token limit failure doesn't crash the entire tree sync.
- **Resource Limits:** If a file has 500 functions, `asyncio.gather(*child_tasks)` will attempt to spin up 500 Cairn Workspaces and 500 LLM calls simultaneously. *Junior Dev Task: You must implement an `asyncio.Semaphore(10)` to limit the concurrency of `process_node` before production.*

**Testing Strategy:** Mock `generate_summary` to just return the string `"MOCK"`. Pass a 3-layer deep tree into `process_node`. Assert that `cairn` created 3 separate workspaces and the final parent node's summary contains the child MOCK strings.

---

## Step 6: The Textual Dashboard (`tui.py`)

**Goal:** Create a live interactive terminal UI that tails `.summary_events.jsonl`.

```python
# src/ast_summary/tui.py
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Log
from pathlib import Path
import json

class AstDashboardApp(App):
    """A Textual dashboard to tail JSONL events."""
    
    BINDINGS = [("q", "quit", "Quit")]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Log(id="event_log", highlight=True)
        yield Footer()

    def on_mount(self) -> None:
        """Start polling the file when the UI boots."""
        self.set_interval(0.2, self.tail_events)
        self.last_line_read = 0

    def tail_events(self) -> None:
        event_file = Path(".summary_events.jsonl")
        if not event_file.exists():
            return
            
        with event_file.open("r", encoding="utf-8") as f:
            lines = f.readlines()
            
        # Only process new lines
        if len(lines) > self.last_line_read:
            log_widget = self.query_one("#event_log", Log)
            for line in lines[self.last_line_read:]:
                data = json.loads(line)
                # Format the UI string
                log_widget.write(f"[{data['event'].upper()}] {data['node']}: {data['message']}")
            
            self.last_line_read = len(lines)

if __name__ == "__main__":
    app = AstDashboardApp()
    app.run()
```

---

## Step 7: The CLI Entrypoint (`cli.py`)

**Goal:** Make it runnable via terminal commands.

```python
# src/ast_summary/cli.py
import typer
import asyncio
from pathlib import Path
from ast_summary.parser import parse_python_file
from ast_summary.engine import process_node
from cairn.runtime.workspace_manager import WorkspaceManager

app = typer.Typer()

@app.command()
def run(filepath: Path):
    """Parse a file and generate recursive summaries."""
    typer.echo(f"Parsing {filepath}...")
    root_node = parse_python_file(filepath)
    
    manager = WorkspaceManager()
    cache_root = Path(".cache/ast_summary")
    
    # Run the async engine
    asyncio.run(process_node(root_node, manager, cache_root))
    typer.echo("Done!")

@app.command()
def ui():
    """Launch the live dashboard."""
    from ast_summary.tui import AstDashboardApp
    AstDashboardApp().run()

if __name__ == "__main__":
    app()
```

### Final Execution Test
To prove it all works:
1. Open Terminal 1: `python -m ast_summary.cli ui`
2. Open Terminal 2: `python -m ast_summary.cli run src/ast_summary/engine.py`

Watch Terminal 1 light up with recursive LLM generations!

---

## Step 8: Real-World End-to-End Testing

Mocking is great for unit tests, but to truly prove the AST Summary Engine works, we need End-to-End (E2E) tests against real files using a local LLM or API.

**Goal:** Create a test suite that processes actual Python, TOML, and Markdown files through the entire pipeline and asserts the validity of the generated summaries.

### 1. The Example Fixtures
Create an `examples/` directory in your project root containing real, structural files:
- `examples/demo_math.py` (Contains a `Calculator` class with `add` and `subtract` methods).
- `examples/demo_config.toml` (Contains `[project]` and `[dependencies]` tables).
- `examples/demo_readme.md` (Contains an H1 and two H2 sections).

### 2. The Integration Test (`test_e2e.py`)
Use `pytest` to run the engine end-to-end on these files.

```python
# tests/test_e2e.py
import pytest
from pathlib import Path
from cairn.runtime.workspace_manager import WorkspaceManager
from ast_summary.parser import parse_python_file
from ast_summary.engine import process_node

@pytest.mark.asyncio
async def test_python_e2e_rollup():
    """Test that a real Python file is parsed, processed, and rolled up."""
    
    # 1. Setup
    target_file = Path("examples/demo_math.py")
    cache_root = Path(".cache/test_ast_summary")
    manager = WorkspaceManager()
    
    # 2. Parse
    root_node = parse_python_file(target_file)
    assert root_node.node_type == "Module"
    assert len(root_node.children) == 1  # The Calculator class
    
    calculator_node = root_node.children[0]
    assert calculator_node.name == "Calculator"
    assert len(calculator_node.children) == 2 # add and subtract
    
    # 3. Execute Engine (Using the REAL LLM client, configured for a fast local model if possible)
    final_summary = await process_node(root_node, manager, cache_root)
    
    # 4. Assertions on the Rollup
    assert final_summary is not None
    assert "Calculator" in final_summary
    
    # Verify the LLM successfully incorporated the child method concepts into the parent summary
    assert "add" in final_summary.lower() or "addition" in final_summary.lower()
    assert "subtract" in final_summary.lower() or "subtraction" in final_summary.lower()
    
    # 5. Verify Cairn Workspaces were created
    workspaces_dir = cache_root / "workspaces"
    assert workspaces_dir.exists()
    
    # There should be 4 workspaces: Module, Class, Add Method, Subtract Method
    workspace_folders = list(workspaces_dir.glob("summary-*"))
    assert len(workspace_folders) == 4
```

### 3. "Gotchas" for E2E Testing
- **LLM Non-Determinism:** LLMs return different text every time. You cannot `assert final_summary == "Specific String"`. You must assert that *key semantic concepts* (like the word "Calculator" or "addition") are present in the output.
- **Cost and Time:** Running E2E tests with real LLMs is slow and costs money/compute. Mark these tests with `@pytest.mark.integration` so they don't run on every single file save during active development, or configure your engine's LLM client to hit a fast/cheap local model like `llama.cpp` or vLLM running a 8B model instead of GPT-4.
- **Cache Teardown:** Make sure your `pytest` fixtures wipe the `.cache/test_ast_summary` directory after every test, otherwise the workspaces will pile up endlessly on your machine.
