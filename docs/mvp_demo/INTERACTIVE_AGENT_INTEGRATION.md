# Integrating Interactive Agents into Remora

Based on a review of the [TUI_DEMO_CONCEPT.md](file:///c:/Users/Andrew/Documents/Projects/remora/TUI_DEMO_CONCEPT.md) and Remora's internal architecture ([kernel_runner.py](file:///c:/Users/Andrew/Documents/Projects/remora/src/remora/kernel_runner.py), [orchestrator.py](file:///c:/Users/Andrew/Documents/Projects/remora/src/remora/orchestrator.py), [externals.py](file:///c:/Users/Andrew/Documents/Projects/remora/src/remora/externals.py), [event_bridge.py](file:///c:/Users/Andrew/Documents/Projects/remora/src/remora/event_bridge.py)), here are the major opportunities for refactoring to support the "standardized agent with interactivity" and dynamic tool management.

## 1. Native `ask_user` External Function

The TUI concept hinges on allowing the agent to pause execution to ask the user a clarifying question (the "Agent Inbox"). 

**Opportunity:** We can seamlessly achieve this by expanding Remora's integration with Grail. 
*   **The Change:** In [src/remora/externals.py](file:///c:/Users/Andrew/Documents/Projects/remora/src/remora/externals.py), we add an `async def ask_user(message: str) -> str:` function alongside [get_node_source](file:///c:/Users/Andrew/Documents/Projects/remora/src/remora/externals.py#37-40) and [run_json_command](file:///c:/Users/Andrew/Documents/Projects/remora/src/remora/externals.py#45-68). 
*   **How it works:** When a `.pym` tool calls `ask_user("Which format?")`, the Python execution suspends. The `ask_user` function emits a new `AGENT_BLOCKED_ON_USER` event (via a newly injected [EventEmitter](file:///c:/Users/Andrew/Documents/Projects/remora/src/remora/events.py#48-58) reference or via an updated [RemoraEventBridge](file:///c:/Users/Andrew/Documents/Projects/remora/src/remora/event_bridge.py#22-154)). It then awaits an `asyncio.Future` specific to that [agent_id](file:///c:/Users/Andrew/Documents/Projects/remora/src/remora/orchestrator.py#62-68).
*   **UI Integration:** The FastAPI server listens for this event, updates the Datastar UI with the input box, and when the user submits their answer, FastAPI resolves the `asyncio.Future`, instantly resuming the `.pym` tool execution natively.

## 2. Dynamic Tool and Prompt Injection (Hot Reloading)

You asked about "being able to really easily add new scripts and modify inputs and prompts and tools and whatnot."

**Opportunity:** Remora's architecture is already primed for this because `KernelRunner.__init__` calls `load_bundle(bundle_path)` dynamically for every new node operation!
*   **The Change:** There is actually very little core refactoring needed here. We simply expose the `agents/<bundle_name>` directory to the web dashboard as a set of editable text files. 
*   **How it works:** Because [GrailToolRegistry](file:///c:/Users/Andrew/Documents/Projects/remora/src/remora/tool_registry.py#42-115) parses the `.pym` files into JSON schemas on the fly when the bundle is loaded, any edits made by the user in the UI (adding a new tool, changing an input schema, updating prompts) take effect immediately for the *next* agent that spins up. 
*   **Enhancement:** To make it even easier, we could add a `ToolBuilder` UI that generates the `inputs.json` and `.pym` boilerplate automatically, dropping it into the active bundle directory.

## 3. Mid-Flight Prompt Injection (Async Inbox)

The TUI concept also mentions a user proactively sending a message to a running agent ("User-Initiated Inbox").

**Opportunity:** This can be natively supported via structured-agents and Remora's `ContextManager`.
*   **The Change:** Provide a mechanism (like a global queue dictionary scoped by [agent_id](file:///c:/Users/Andrew/Documents/Projects/remora/src/remora/orchestrator.py#62-68)) where the UI can drop text messages.
*   **How it works:** Update `KernelRunner._provide_context()` or create a hook into the structured-agents `AgentKernel` that checks this queue between LLM turns. If a message is found, we inject it directly into the `AgentKernel`'s conversation history as a "system" or "user" message before making the next inference request.

## Summary
By leveraging **Grail's external functions** for blocking UI prompts and **structured-agents' context providers** for async message injection, Remora can achieve the "Interactive Standardized Agent" dream with very minimal structural disruption. The agent logic remains completely isolated from the web server logic.
