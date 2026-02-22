# Remora - Low Priority Refactoring Guide

This guide provides step-by-step instructions to implement the three low-priority recommendations from the Remora Code Review: **Model Flexibility**, **Documentation Sync**, and **Performance Profiling**. Each section includes necessary code snippets and details on how to test your changes.

Since Remora is a new library, **backward compatibility is not a concern**. Focus on clean, elegant architecture.

---

## 1. Model Flexibility

**Objective:** Allow configuring non-FunctionGemma models through Remora's configuration. Currently, the system assumes `google/functiongemma-270m-it` and the `function_gemma` plugin in several places.

### Step 1.1: Update `RemoraConfig`
We need to add support for a `model_plugin` configuration parameter along with `model_id`.
In `src/remora/config.py`:

Modify `ServerConfig`:
```python
class ServerConfig(BaseModel):
    base_url: str = "http://remora-server:8000/v1"
    api_key: str = "EMPTY"
    timeout: int = 120
    default_adapter: str = "google/functiongemma-270m-it"
    default_plugin: str = "function_gemma"  # Add this line
    retry: RetryConfig = Field(default_factory=RetryConfig)
```

Modify `OperationConfig`:
```python
class OperationConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    enabled: bool = True
    auto_accept: bool = False
    subagent: str
    model_id: str | None = None
    model_plugin: str | None = None  # Add this line
    priority: Literal["low", "normal", "high"] = "normal"
```

In `RemoraConfig.validate_and_resolve_precedence(self)`, ensure `model_plugin` inherits properly:
```python
        # 2. Model Adapter precedence
        if hasattr(self, 'operations') and hasattr(self, 'server'):
            for op_name, op_config in self.operations.items():
                if getattr(op_config, 'model_id', None) is None:
                    op_config.model_id = self.server.default_adapter
                # Add this inherited fallback logic:
                if getattr(op_config, 'model_plugin', None) is None:
                    op_config.model_plugin = self.server.default_plugin
```

### Step 1.2: Pass Configuration to structured-agents
In `src/remora/kernel_runner.py`, `KernelRunner._build_kernel` currently falls back to `self.config.server.default_adapter`. We should also provide logic to resolve the plugin override dynamically if structured-agents supports it, or instantiate the correct plugin.

```python
    def _build_kernel(self) -> AgentKernel:
        # Resolve model configuration
        op_config = self.config.operations.get(self.bundle.name)
        
        # Override bundle manifest if the Remora config explicitly defines them
        bundled_adapter = self.bundle.manifest.model.adapter
        model_id = op_config.model_id if op_config and op_config.model_id else (bundled_adapter or self.config.server.default_adapter)
        
        bundled_plugin = self.bundle.manifest.model.plugin
        model_plugin_name = op_config.model_plugin if op_config and op_config.model_plugin else (bundled_plugin or self.config.server.default_plugin)
        
        kernel_config = KernelConfig(
            base_url=self.config.server.base_url,
            model=model_id,
            api_key=self.config.server.api_key,
            timeout=float(self.config.server.timeout),
            max_tokens=self.config.runner.max_tokens,
            temperature=self.config.runner.temperature,
            tool_choice=self.config.runner.tool_choice,
        )
        # Remaining logic handles GrailBackendConfig ...
```

*Note: You will also likely need to modify `structured-agents`' `get_plugin()` behavior to initialize the overridden plugin by name if the user changes it.*

### Step 1.3: Update `structured-agents`
To cleanly resolve the plugin override dynamically, we must update the underlying `structured-agents` library to accept an optional override when retrieving the bundle's plugin. 

Please see **[STRUCTURED_AGENTS_FUNCTIONALITY_REFACTOR.md](./STRUCTURED_AGENTS_FUNCTIONALITY_REFACTOR.md)** for detailed instructions on modifying `structured-agents` to support this dynamic override.

With the changes from that guide applied, `KernelRunner._build_kernel` in Remora can cleanly retrieve the overridden plugin:
```python
        # In src/remora/kernel_runner.py
        plugin = self.bundle.get_plugin(model_plugin_name)
```

### Step 1.4: Testing
**Automated Tests:**
- Update `tests/test_config.py` to verify `default_plugin` parsing and precedence resolution.
- Ensure `model_plugin` is correctly propagated through `RemoraConfig` to `KernelRunner`.

---

## 2. Documentation Sync

**Objective:** Clean up the deprecated, redundant `remora.subagent` module. Remora parses subagents internally to check Grail validation, while it actually executes them using `structured_agents.bundles`. This duplication creates sync drift.

### Step 2.1: Delete `subagent.py` and its tests
- Remove `src/remora/subagent.py` entirely.
- Remove `tests/test_subagent.py` entirely.

### Step 2.2: Refactor `list-agents` in CLI
In `src/remora/cli.py`, the `list-agents` command uses `load_subagent_definition` solely to check Grail validation and compilation warnings. Let's rewrite this part using `structured_agents` directly.

Update imports in `src/remora/cli.py`:
```python
# Remove: from remora.subagent import load_subagent_definition
from structured_agents import load_bundle
```

Modify the loop inside `list_agents` command:
```python
        # Check Grail validation
        grail_valid = False
        grail_warnings = []
        if yaml_exists:
            try:
                # Load via structured-agents instead
                bundle = load_bundle(yaml_path.parent)
                # Note: Assuming bundle provides a way to validate tools, 
                # or you directly use GrailToolRegistry here if structured_agents doesn't.
                # If structured_agents does not expose grail_summary natively, 
                # instantiate GrailToolRegistry from remora.tool_registry to validate the bundle's tools.
                from remora.tool_registry import GrailToolRegistry
                registry = GrailToolRegistry(config.agents_dir)
                catalog = registry.build_tool_catalog(bundle.tool_definitions) # Psuedo-code depending on struct-agents API
                grail_valid = catalog.grail_summary.get("valid", False)
                grail_warnings = catalog.grail_summary.get("warnings", [])
            except Exception:
                pass
```
*Note: Depending on how `structured-agents` stores tool representations, you may need to map them slightly to `GrailToolRegistry.build_tool_catalog()` arguments.*

### Step 2.3: Remove redundant code in Factories and Docs
- In `src/remora/testing/factories.py`, remove all references and mocks that use `SubagentDefinition`, `ToolDefinition`, or `InitialContext`. Update to use `structured-agents` test utilities.
- In `docs/API_REFERENCE.md`, remove the section referencing `remora.subagent`.

### Step 2.4: Testing
**Automated Tests:**
- Run `uv run pytest tests/test_cli.py` and ensure the tests for `list-agents` still pass.
- Since we deleted a module, ensure all other tests compile by running the entire test suite.

---

## 3. Performance Profiling

**Objective:** Help identify bottlenecks when running Remora on larger codebases by adding a built-in `--profile` flag that outputs a `cProfile` trace.

### Step 3.1: Add `--profile` CLI Argument
In `src/remora/cli.py`, update the `analyze` command signature to include a profile flag:

```python
    # Add to the end of analyze()'s arguments:
    profile: bool = typer.Option(
        False,
        "--profile",
        help="Run using cProfile and save to .remora/profile.prof",
    ),
```

### Step 3.2: Wrap Execution in cProfile
Still in `src/remora/cli.py` under the `analyze` command, import `cProfile` and wrap the asynchronous loop execution:

```python
    import cProfile
    import pstats

    # ... Existing analyzer and _run logic ...

    if profile:
        console.print("[yellow]Running with performance profiling enabled...[/yellow]")
        profiler = cProfile.Profile()
        profiler.enable()
        
        results = asyncio.run(_run())
        
        profiler.disable()
        # Save profile data
        profile_path = Path(".remora/profile.prof")
        profile_path.parent.mkdir(parents=True, exist_ok=True)
        profiler.dump_stats(profile_path)
        
        console.print(f"\n[bold green]Profile saved to {profile_path}[/bold green]")
        console.print("View it using: [cyan]snakeviz .remora/profile.prof[/cyan]")
        raise typer.Exit(_exit_code(results))
    else:
        results = asyncio.run(_run())
        raise typer.Exit(_exit_code(results))
```

### Step 3.3: Ensure Profiling Ignore Patterns
In `src/remora/config.py`, verify `.remora` directory is added to `WatchConfig`'s `ignore_patterns` list if it's not already, to prevent continuous reloading loop if a user runs `watch` mode with profiling (if you add profiling to watch mode as well).

### Step 3.4: Testing
**Manual Testing:**
1. Run `remora analyze src/ --profile`.
2. Verify the console prints the yellow profiling warning.
3. Once finished, verify `.remora/profile.prof` exists in the filesystem.
4. Optionally, install `snakeviz` (`pip install snakeviz`) and run `snakeviz .remora/profile.prof` to verify the generated stats visualizer opens properly without corruption.

---

## 4. Dynamic LoRA Adapter Routing

**Objective:** Ensure Remora can route inference requests to specific LoRA adapters on a call-by-call basis. 

### Operation-Level Configuration
As of vLLM's OpenAI-compatible API architecture, a specific LoRA adapter is targeted simply by passing the adapter's name (or ID) as the `model` parameter. 

Because of this, **the changes implemented in Step 1 already satisfy operation-level LoRA configuration.** By setting an operation's `model_id` to a LoRA adapter's name in `remora.yaml`, Remora will send that name as the `model` param to vLLM.

### Per-Call Dynamic Overrides
However, if we need to dynamically switch the LoRA adapter mid-session based on agent state or tooling (a feature critical for Remora), we must modify `structured-agents` directly so that the `model` parameter is evaluated *per-inference-loop* rather than locked at `LLMClient` initialization.

Please refer to **[STRUCTURED_AGENTS_FUNCTIONALITY_REFACTOR.md](./STRUCTURED_AGENTS_FUNCTIONALITY_REFACTOR.md)** for a deep dive and line-by-line instructions on implementing dynamic per-call model overrides in `structured-agents`.

Once those underlying library changes are implemented, you can surface the override in Remora by updating `_provide_context` within `src/remora/kernel_runner.py` so prompt injections can trigger the swop (e.g., if you store a `target_lora` variable in the `ContextManager`):

```python
    async def _provide_context(self) -> dict[str, Any]:
        await self.context_manager.pull_hub_context()
        prompt_ctx = self.context_manager.get_prompt_context()

        return {
            "node_text": self.node.text,
            "target_file": str(self.node.file_path),
            "workspace_id": self.ctx.agent_id,
            "agent_id": self.ctx.agent_id,
            "workspace_path": str(self.workspace_path) if self.workspace_path else None,
            "stable_path": str(self.stable_path) if self.stable_path else None,
            "node_source": self.node.text,
            "node_metadata": {
                "name": self.node.name,
                "type": str(self.node.node_type),
                "file_path": str(self.node.file_path),
                "node_id": self.node.node_id,
            },
            "model_override": prompt_ctx.get("target_lora"), # Inject dynamic LoRA name
            **prompt_ctx,
        }
```
