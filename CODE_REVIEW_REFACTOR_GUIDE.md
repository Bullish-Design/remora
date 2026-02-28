# Remora Reactive Swarm: Comprehensive Refactoring Guide

This guide provides exact, step-by-step instructions and code snippets necessary to implement the missing components, remove vestigial code, and complete the transition of the Remora library to the unified Reactive Swarm architecture. This document is designed to be fully actionable for developers new to the codebase.

## Phase 1: Swarm Communication Tools

To enable agents to communicate and organize themselves dynamically, they need native tools. We must create the tools and wire the execution environment to support them.

### Step 1.1: Create `swarm.py` Tools
**File**: `src/remora/core/tools/swarm.py` (New File)

Create a new file that defines the `send_message` and `subscribe` tools. These tools rely on callbacks provided by the `SwarmExecutor` via the `externals` dictionary.

```python
"""Swarm communication tools for agents."""

from typing import Any
from structured_agents import Tool
from remora.core.events import AgentMessageEvent
from remora.core.subscriptions import SubscriptionPattern

def build_swarm_tools(externals: dict[str, Any]) -> list[Tool]:
    """Build tools for swarm communication."""
    emit_event = externals.get("emit_event")
    register_subscription = externals.get("register_subscription")
    agent_id = externals.get("agent_id")
    correlation_id = externals.get("correlation_id")

    async def send_message(to_agent: str, content: str) -> str:
        """Send a direct message to another agent in the swarm."""
        if not emit_event or not agent_id:
            return "Error: Swarm event emitter is not configured."
        
        event = AgentMessageEvent(
            from_agent=agent_id,
            to_agent=to_agent,
            content=content,
            correlation_id=correlation_id
        )
        # Emit the event; EventStore will route it to the target agent
        await emit_event("AgentMessageEvent", event)
        return f"Message successfully queued for {to_agent}."

    async def subscribe(
        event_types: list[str] | None = None, 
        from_agents: list[str] | None = None, 
        path_glob: str | None = None
    ) -> str:
        """Dynamically subscribe to swarm events."""
        if not register_subscription or not agent_id:
            return "Error: Subscription registry is not configured."
            
        pattern = SubscriptionPattern(
            event_types=event_types,
            from_agents=from_agents,
            to_agent=agent_id,
            path_glob=path_glob
        )
        await register_subscription(agent_id, pattern)
        return "Subscription successfully registered."

    return [
        Tool.from_function(send_message),
        Tool.from_function(subscribe)
    ]
```

### Step 1.2: Register Swarm Tools in Grail Discovery
**File**: `src/remora/core/tools/grail.py`

Update the `discover_grail_tools` function to automatically include the swarm tools for every agent.

**1. Add the import at the top of the file:**
```python
from remora.core.tools.swarm import build_swarm_tools
```

**2. Modify the return logic to include our new tools:**
Find the `discover_grail_tools` function and append the tools before returning.
```python
    # ... existing logic that discovers tools into `tools` list ...
    
    # Add Swarm Tools unconditionally if externals are provided
    if externals:
        tools.extend(build_swarm_tools(externals))
        
    return tools
```

### Step 1.3: Plumb EventStore to SwarmExecutor Externals
**File**: `src/remora/core/swarm_executor.py`

Pass the required callbacks into the `externals` dictionary so the tools can use them.

**1. Update `SwarmExecutor.__init__` to accept `subscriptions`:**
```python
    def __init__(
        self,
        config: "Config",
        event_bus: "EventBus | None",
        event_store: EventStore,
        subscriptions: SubscriptionRegistry, # <-- ADD THIS
        swarm_id: str,
        project_root: Path,
    ):
        self.config = config
        self._event_bus = event_bus
        self._event_store = event_store
        self._subscriptions = subscriptions    # <-- ADD THIS
        # ...
```
*(Also update `src/remora/core/agent_runner.py` around line 133 to pass `self._subscriptions` when it instantiates `SwarmExecutor`.)*

**2. Inject the callbacks into `externals` in `run_agent`:**
Locate the part of `run_agent` where `externals` is retrieved, and add the event bridge methods.
```python
        await self._workspace_service.initialize()
        workspace = await self._workspace_service.get_agent_workspace(state.agent_id)
        externals = self._workspace_service.get_externals(state.agent_id, workspace)

        # --- ADD THESE LINES ---
        externals["agent_id"] = state.agent_id
        externals["correlation_id"] = getattr(trigger_event, "correlation_id", None) if trigger_event else None
        
        async def _emit_event(event_type: str, event_obj: Any) -> None:
            await self._event_store.append(self._swarm_id, event_obj)
            
        async def _register_sub(agent_id: str, pattern: Any) -> None:
            await self._subscriptions.register(agent_id, pattern)
            
        externals["emit_event"] = _emit_event
        externals["register_subscription"] = _register_sub
        # -----------------------
```

## Phase 2: Fixing Agent Runner Lifecycle & Context

The executor does not correctly persist conversational memory or execute correlation cascades properly.

### Step 2.1: Context Tracking in `AgentState`
**File**: `src/remora/core/swarm_executor.py`

Delete the vestigial `ContextBuilder` logic and natively persist interactions into `AgentState.chat_history`. 

**1. Inject Chat History into Kernel Execution:**
Locate the `_run_kernel` method inside `SwarmExecutor`. Instead of just building a single system and user message prompt, we must inject the agent's persistent `chat_history`.

```python
    # Inside _run_kernel:
    try:
        messages = [
            Message(role="system", content=manifest.system_prompt),
        ]
        
        # --- ADD HISTORY ---
        for msg in getattr(state, "chat_history", []):
            messages.append(Message(role=msg["role"], content=msg["content"]))
        # -------------------

        messages.append(Message(role="user", content=prompt))
        
        # ... existing kernel run logic ...
```
*(You will need to pass `state: AgentState` into the `_run_kernel` signature: `async def _run_kernel(self, state: AgentState, manifest: Any, prompt: str, tools: list[Any], *, model_name: str)` and update the `run_agent` call to match).*

**2. Save Turn History on Completion:**
Still inside `SwarmExecutor.run_agent`, after `_run_kernel` completes, we must persist the new user prompt and the resulting AI response back into the `state.chat_history` list so it will be saved correctly.

```python
        # Inside run_agent, after returning from _run_kernel:
        result = await self._run_kernel(state, manifest, prompt, tools, model_name=model_name)
        
        response_text = str(result)
        truncated_response = truncate(response_text, max_len=self.config.truncation_limit)
        
        # --- ADD THESE LINES TO PERSIST STATE ---
        state.chat_history.append({"role": "user", "content": prompt})
        state.chat_history.append({"role": "assistant", "content": truncated_response})
        # Keep window size manageable (e.g., last 10 messages)
        state.chat_history = state.chat_history[-10:]
        # ----------------------------------------

        return truncated_response
```

### Step 2.2: Track `correlation_id` in `AgentRunner`
**File**: `src/remora/core/agent_runner.py`

To prevent infinite loops, `AgentRunner` relies on tracing `correlation_id` values across cascades (when Agent A triggers Agent B which triggers Agent C). `AgentRunner` passes the `trigger_event` to the `SwarmExecutor`, and we set it in `externals` in step 1.3.

**Verify Cascade Depth Propagation:**
Ensure that when a `ContentChangedEvent` or `AgentMessageEvent` starts a cascade, a consistent random string is assigned to it and tracked.

```python
    # Inside `_process_trigger` in agent_runner.py:
    async def _process_trigger(self, agent_id: str, event_id: int, event: RemoraEvent) -> None:
        # Make sure correlation id exists in incoming events:
        correlation_id = getattr(event, "correlation_id", None) or getattr(event, "id", None) or "base"
        
        # Add a correlation key track in self._depths:
        key = f"{agent_id}:{correlation_id}"
        current_depth = self._depths.get(key, 0)
        
        if current_depth >= self._config.max_trigger_depth:
            logger.warning(f"Cascade limit reached for {key}")
            return
            
        self._depths[key] = current_depth + 1
        
        # ... proceed to execute turn ...
```

## Phase 3: Reconciler and Startup Synchronization

The startup hook fails to recognize offline changes and there is no Jujutsu (VCS) tracking.

### Step 3.1: Content Diffing in `reconciler.py`
**File**: `src/remora/core/reconciler.py`

We need to emit `ContentChangedEvent` upon realizing an existing CST node's content has changed while the daemon was down.

**Locate `reconcile_on_startup` and add an intersection loop:**
Currently the script iterates over `new_ids` to create agents, and `deleted_ids` to orphan agents. Add a loop to iterate over `existing_ids & discovered_ids` (the intersection).

```python
    # Keep the existing loops for new_ids and deleted_ids
    
    # --- ADD THIS LOOP TO CHECK FOR MODIFIED FILES OFFLINE ---
    from remora.core.agent_state import load as load_agent_state
    import time
    
    updated = 0
    common_ids = discovered_ids.intersection(existing_ids)
    
    for node_id in common_ids:
        node = node_map[node_id]
        
        try:
            state_path = get_agent_state_path(swarm_root, node.node_id)
            state = load_agent_state(state_path)
            
            # Check if file was modified while agent was asleep
            file_mtime = Path(node.file_path).stat().st_mtime
            if state.last_updated < file_mtime:
                # File changed offline!
                if event_store is not None:
                    from remora.core.events import ContentChangedEvent
                    relative_path = to_project_relative(project_path, node.file_path)
                    
                    event = ContentChangedEvent(
                        path=relative_path,
                        diff="File modified while daemon offline."
                    )
                    # Emit so the agent reacts to changes it missed
                    await event_store.append("reconciler", event)
                
                updated += 1
                
                # Update the state timestamp so we don't infinitely trigger
                state.last_updated = time.time()
                save_agent_state(state_path, state)
                
        except Exception as e:
            logger.warning(f"Failed to reconcile state for {node_id}: {e}")
    # ---------------------------------------------------------
```

### Step 3.2: Jujutsu (jj) Overlay Source Control
**File**: `src/remora/core/swarm_executor.py`

Provide one-way sync. Remora commands state into JJ commits dynamically.

**1. Create a post-agent-run commit hook:**
At the end of `run_agent`, implement a subprocess call anytime an agent completes a successful turn that modifies standard files.

```python
    # Inside run_agent, just before `return truncated_response`:
    
    # --- ADD JJ SNAPSHOT LOGIC ---
    import subprocess
    try:
        # Fast check if the project is a JJ repo
        if (self._project_root / ".jj").exists():
            message = f"Agent {state.agent_id} completed turn."
            
            # Create a snapshot commit asynchronously
            process = await asyncio.create_subprocess_exec(
                "jj", "commit", "-m", message,
                cwd=str(self._project_root),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
            await process.wait()
    except Exception as e:
        logger.warning(f"Failed to create JJ commit: {e}")
    # -----------------------------
```

## Phase 4: Neovim Event Bridge Corrections

The editor relies on saving buffers to synchronize state.

### Step 4.1: Handle Generic Events in RPC
**File**: `src/remora/nvim/server.py`

Accept arbitrary JSON events instead of strictly checking for only two specific strings.

**Locate `_handle_swarm_emit`:**
```python
    async def _handle_swarm_emit(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle swarm.emit method."""
        event_type = params.get("event_type")
        event_data = params.get("data", {})
        
        # ... existing if/elif blocks ...
```

**Replace the conditional block with dynamic instantiation:**
```python
    import remora.core.events as events_module
    
    async def _handle_swarm_emit(self, params: dict[str, Any]) -> dict[str, Any]:
        event_type = params.get("event_type")
        event_data = params.get("data", {})
        
        try:
            # Dynamically get the event class from the events module
            event_class = getattr(events_module, str(event_type))
            
            # Pre-process paths if it's a content event
            if "path" in event_data:
                event_data["path"] = str(to_project_relative(self._project_root, event_data["path"]))
                 
            # Instantiate the dataclass
            event = event_class(**event_data)
            
        except (AttributeError, TypeError) as e:
            raise ValueError(f"Unknown or invalid event type mapping: {event_type}. Error: {e}")

        await self._event_store.append("nvim", event)
        return {"status": "ok"}
```
*(This ensures `FileSavedEvent` and other editor-driven events gracefully enter the queue for indexing and agent reactions without triggering string-matching ValueError crashes.)*

## Phase 5: Eradication of Legacy Systems

Clean up code that doesn't fit the reactive paradigm.

### Step 5.1: Delete `tool_registry.py`
**File**: `src/remora/core/tool_registry.py`

Remove the file entirely, as the dependency injection container/registry paradigm is obsolete. 

**Refactor `grail.py`:**
Change `src/remora/core/tools/grail.py` to directly instantiate and return a list of `Tool` objects natively instead of importing them through `ToolRegistry`.

```python
# In src/remora/core/tools/grail.py
# Remove all `ToolRegistry` dependencies.

def build_file_ops(workspace: Any) -> list[Tool]:
    async def read_file(path: str) -> str:
        return await workspace.read_file(path)
    # ... define list_dir, write_file, etc ...
    return [
        Tool.from_function(read_file),
        # ...
    ]

# And explicitly call them in `discover_grail_tools`:
def discover_grail_tools(
    # ...
) -> list[Tool]:
    tools = []
    
    # Add generic tools explicitly
    # tools.extend(build_file_ops(workspace))
    
    # Add Swarm tools as done in Phase 1
    if externals:
        from remora.core.tools.swarm import build_swarm_tools
        tools.extend(build_swarm_tools(externals))
        
    return tools
```

### Step 5.2: Purge `executor.py` Graph Engine
**Files**: `src/remora/core/executor.py`, `src/remora/core/graph.py`

*   **Action**: Eliminate topological batch processing overlaps.
*   **Implementation**: Simplify the legacy graph topological batch mode to bare minimum since it is only retained for backwards-compatibility or strictly enforced sequential pipelines. Rip out any deep contextual tracking logic inside the `executor.py` module since memory execution relies fully on `AgentRunner` triggers and `SwarmExecutor` now.
