# xgrammar-tools Concept & Remora Refactor

Date: 2026-02-21

This document outlines the architectural end-state for a two-part system transformation: creating a new, dedicated library called `xgrammar-tools` in a separate repository, followed by a drastic simplification of the `remora` codebase to depend on it.

We are treating this as a clean break. There are no backward compatibility requirements. The goal is the best possible architecture for structured tool execution and agent orchestration.

---

## Part 1: The `xgrammar-tools` Library

### 1.1 Core Philosophy

`xgrammar-tools` is an opinionated, standalone library responsible for:
1. **Structured Tool Orchestration**: Guaranteeing model output format via XGrammar and executing tool calls.
2. **vLLM Configuration Ownership**: Defining the schemas and defaults for how the local inference server is queried.
3. **Execution Backends**: Providing a first-class `.pym` script executor, while allowing pure Python or RPC backends.

It is *not* responsible for multi-agent workflows, code discovery, or workspace state management (those belong in Remora).

### 1.2 Plugin Bundles (Models, Prompts, Tools)

A key requirement is the ability to drop in bundles consisting of custom LoRA adapters, `.pym` tools, XGrammar structural tags, and specific models.

#### Bundle Options

- **Option A: Python Packages (`entry_points`)**. Bundles are distributed as `pip` installable packages.
  - *Pros*: Standard Python ecosystem distribution, easy dependency resolution.
  - *Cons*: Heavyweight to create, requires environment rebuilds to add a new prompt or tool, poor fit for asset-heavy payloads (LoRA weights, `.pym` scripts).
- **Option B: Directory-Based Asset Bundles.** Bundles are directories on disk containing a `manifest.yaml`, prompt templates, `.pym` scripts, and relative paths to LoRAs/model weights.
  - *Pros*: Language-agnostic assets. Incredibly easy to hot-reload, modify on the fly, and store in a Git repository or zip file. Fits the "agent as data" paradigm.
  - *Cons*: Requires writing a custom manifest parser and loader in the library.

**Recommendation: Option B (Directory-Based Bundles)**
We will use Directory-Based Asset Bundles. `xgrammar-tools` will include a `BundleLoader` that points to a local directory or remote repository. The library defines a strict schema for `bundle.yaml`, which declares the model target, the required LoRA adapters, the expected grammar strategy, and points to the bundled `.pym` scripts. This perfectly isolates agent *behavior* from the core orchestration engine.

#### Plugin Interfaces

The core engine will provide specific Model Plugins to handle the quirks of how different families of models expect tool calls to be formatted.
We will validate this interface by implementing two model plugins out of the gate:
1. `FunctionGemmaPlugin`
2. `QwenPlugin` (targeted at Qwen/Qwen2.5-3B-Instruct)

### 1.3 Event Streaming and Observability

`xgrammar-tools` needs to be observable without coupling it directly to Remora's specific TUI or logging needs.

#### Options

- **Option A: Async Generator.** The `Kernel.run()` method `yields` events mid-flight instead of `return`ing.
- **Option B: Callback Protocol.** The `Kernel` accepts an optional `EventSubscriber` object, calling methods like `on_model_request()` or `on_tool_result()`.

**Recommendation: Async Callback Protocol**
We will define an `EventCallback` protocol in `xgrammar-tools`. 
The library itself will use standard Python `logging` for detailed debug traces. However, when instantiated, you can pass an `EventCallback` instance to the `Kernel`. As the Kernel loops through prompt building, model invocation, and tool execution, it fires structured event dataclasses to this callback. 

This allows `remora` to pass in a bridging callback that translates these core events into its own `EventEmitter` stream for the Rich TUI, maintaining perfect visibility without polluting `xgrammar-tools` with TUI-specific concepts.

### 1.4 API Sketch

```python
from xgrammar_tools import ToolKernel, KernelConfig
from xgrammar_tools.plugins import QwenPlugin
from xgrammar_tools.bundles import load_bundle

# 1. Load a bundle from disk (contains tools, prompts, lora config)
bundle = load_bundle("./my-custom-agent-bundle")

# 2. Configure the kernel
kernel = ToolKernel(
    config=KernelConfig(base_url="http://localhost:8000"),
    plugin=QwenPlugin(),
    tools=bundle.tools,
)

# 3. Define an observer for real-time TUI streaming
class RemoraObserver:
    async def on_model_request(self, event): ...
    async def on_tool_result(self, event): ...

# 4. Execute
result = await kernel.run(
    prompt=bundle.render_prompt(inputs={"file": "foo.py"}),
    observer=RemoraObserver(),
)

print(result.text, result.tool_results)
```

---

## Part 2: Remora Refactor

Once `xgrammar-tools` is built in its own repository, we will aggressively refactor `remora` to be a pure, composed orchestration layer.

### 2.1 What Remora Loses (Deleted Code)
- `src/remora/grammar.py` (Moved to xgrammar-tools)
- `src/remora/tool_parser.py` (Moved to xgrammar-tools)
- `src/remora/execution.py` (The Grail `.pym` executor moves to xgrammar-tools)
- The entire `while turn_count < max_turns` loop in `src/remora/runner.py`.

### 2.2 What Remora Keeps (Refocused Code)
- **CST Discovery (`src/remora/discovery/*`)**: Parsing the user's project to find injection nodes.
- **Context & Hub Integration (`src/remora/context/*`)**: Managing KV state, summarizing recent actions, and interacting with Cairn Hub memory.
- **Orchestration (`src/remora/orchestrator.py`)**: Managing task queues, concurrency, and routing nodes to the correct agent bundles.
- **CLI & TUI (`src/remora/cli.py`)**: The developer user experience and real-time dashboard.

### 2.3 The New Remora Runner

The `FunctionGemmaRunner` inside Remora will be replaced by a simple wrapper that bridges Remora's state to `xgrammar-tools`.

```python
class XGrammarRunner:
    """Remora's wrapper around xgrammar-tools."""
    
    def __init__(self, node: CSTNode, context: RemoraAgentContext):
        self.node = node
        self.context = context
        # Remora loads the bundle
        self.bundle = load_bundle(config.agent_bundle_path)
        
    async def run(self) -> AgentResult:
        kernel = ToolKernel(plugin=self.bundle.get_plugin())
        observer = RemoraEventBridge(self.context.agent_id)
        
        # xgrammar-tools handles the loop, grammar, and tools!
        result = await kernel.run(
            prompt=self.bundle.render(self.node),
            observer=observer
        )
        
        return self._format_final_result(result)
```

### 2.4 Conclusion

This architecture completely unbinds the mechanics of structured tool execution from the conceptual problem of multi-agent codebase modification. It allows standard infrastructure (like vLLM and XGrammar) to be abstracted away into an easily tested `xgrammar-tools` library, letting Remora focus entirely on navigating code and managing agent state.
