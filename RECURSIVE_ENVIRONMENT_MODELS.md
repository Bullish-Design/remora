<!-- c:\Users\Andrew\Documents\Projects\remora\RECURSIVE_ENVIRONMENT_MODELS.md -->

# Recursive Environment Models (REMs): Concept & Directions

**Status:** Conceptual Riffing
**Context:** Merging the theory of Recursive Language Models (RLMs) with Remora's existing architectural patterns (Cairn KV, Grail Sandbox, Tree-sitter AST).

---

## The Core Concept: From RLM to REM

Standard RLMs (Recursive Language Models) view the "environment" as a simple Python REPL holding a massive string of context. 

In Remora, we can reframe this into **Recursive Environment Models (REMs)**. Here, the "Environment" is not just a bland REPL; it is a **highly structured, context-aware Sandbox** (powered by Grail and Cairn) that bounds the LLM's reality. When an LLM recursively spawns a sub-task, it isn't just calling another LLM—it is spinning up a new, tightly-scoped *Environment* tailored specifically for the sub-task.

Grounding this in the `examples/treesitter_swarm` and the `FEATURE_ASSEMBLY_LINE_CONCEPT`, here are three distinct directions we can take this paradigm:

### 1. Spatial Recursion: "AST Sub-Graph Environments"

*Inspiration: `examples/TREESITTER_AGENT_SWARM_CONCEPT.md`*

**The Concept:**
Instead of passing the entire codebase to a single logic model as a massive string prompt, the Root Architect is placed in a sandbox where the *Tree-sitter AST is a queryable object*. The model operates programmatically on the tree, completely unconstrained by strict traversal rules.

For example, when refactoring an API:
1. The Root Environment receives the codebase as an accessible AST object rather than text.
2. The agent writes simple Python scripts in its REPL sandbox to interact with the AST (e.g., `ast_graph.find_functions(name_contains="get_", return_type="dict")`). 
3. Based on what its programmatic queries return, it dynamically isolates a subset of the graph.
4. It recursively spawns sub-environments, injecting *only* that isolated sub-graph context, and dynamically loads the appropriate LoRA adapter (e.g., a "function_definition_expert") to execute localized refactoring tasks.

**Remora Implementation Mappings:**
*   **Agent Bundles Required:**
    *   `architect`: The Root Agent. Loaded with `function_gemma` and an `architect-v1` LoRA. It is the only agent that receives the global `ast_graph`.
    *   `node_implementer`: The spawned worker agent. It is passed specific `node_ids` to construct its localized Cairn Workspace Bridge.
*   **Grail Tools (`.pym`) Required:**
    *   `query_ast.pym`:
        *   **Functionality:** Allows the Architect to write and execute basic python traversal scripts against the Tree-sitter AST Graph object in its sandbox.
        *   **Inputs:** `script: str` (The Python execution sequence).
        *   **Outputs:** JSON representation of discovered `TreeNode` objects (IDs, types, and file locations).
    *   `spawn_node_environment.pym`:
        *   **Functionality:** The trigger to initiate the fan-out recursion. Tells the `Coordinator` to batch new tasks for the identified nodes.
        *   **Inputs:** `node_ids: list[str]`, `target_agent: str` (e.g., `"node_implementer"`), `intent: str`.
        *   **Outputs:** `task_ids: list[str]` representing the newly spawned sub-tasks on the Hub daemon.

### 2. Temporal Recursion: "The Assembly Line Sandbox"

*Inspiration: `examples/FEATURE_ASSEMBLY_LINE_CONCEPT.md`*

**The Concept:**
Recursion in code usually implies drilling *down* into data structures. But we can also recurse *forward in time* across the feature lifecycle. 

1. A user requests a feature.
2. The Root Model enters the **Planning Environment**.
3. Upon finalizing the plan, the Planning Environment dynamically executes code to construct and launch the **Implementation Environment**, passing only the architectural constraints as the environment state in Cairn KV.
4. If the Implementation Environment encounters an error, it doesn't just fail; it dynamically constructs a **Debugging Environment**, injecting the stack trace as the primary context variable, and recurses into it.

**Remora Implementation Mappings:**
*   **Agent Bundles Required:**
    *   `planner`: Analyzes requirements and drafts the `implementation_plan.md`.
    *   `implementer`: Actually executes the Grail commands to mutate the codebase.
    *   `debugger`: Injected purely with stack-traces and diffs if the `implementer`'s verification tests fail.
*   **Grail Tools (`.pym`) Required:**
    *   `transition_phase.pym`:
        *   **Functionality:** Suspends the current task and spawns a new Temporal Environment running a different Agent Bundle. Writes the "constraints" payload to the `remora.hub.db` for the next agent to read.
        *   **Inputs:** `next_bundle_name: str` (e.g., `"implementer"`), `state_constraints: dict`.
        *   **Outputs:** Terminates the current agent session; Coordinator returns an event stream confirmation that the next phase has started.
    *   `spawn_debugging_environment.pym`:
        *   **Functionality:** An error-handler tool specifically for the `implementer`. Instead of trying to fix the bug itself, it recurses into a dedicated `debugger` environment.
        *   **Inputs:** `failing_test_command: str`, `stack_trace: str`, `recent_diffs: str`.
        *   **Outputs:** `debugging_task_id: str` (The implementer waits for this task to complete before continuing).

### 3. Memory-Bus Recursion: "The Cairn Context Tree"

*Inspiration: `examples/treesitter_swarm/README.md` (The "Shared Swarm Memory Bus" solution)*

**The Concept:**
In a standard RLM, passing context down to a sub-call requires serializing it into the prompt. In a REM, environments share an asynchronous memory bus (Cairn KV).

1. The Root Architect creates a task intent and saves it to Cairn: `KV.set("task_intent", "Add rate limiting")`.
2. It spawns a Sub-Environment to handle `routes.py`.
3. The Sub-Environment *doesn't* get the full intent in its system prompt. Instead, its REPL has an exposed `bus.get("task_intent")` tool. 
4. The Sub-Model dynamically queries its parent's environment state only when it needs clarification.

**Remora Implementation Mappings:**
*   **Agent Bundles Required:**
    *   Any agent bundle spun up as a "Sub-Task" (e.g., `node_implementer`, `debugger`). Their initial system prompt is injected *only* with `Task ID: <uuid>`.
*   **Grail Tools (`.pym`) Required:**
    *   `hub_memory_write.pym`:
        *   **Functionality:** Allows a Parent Agent to construct the "Context Tree" by writing key-value configuration or intent payloads directly to the Hub Daemon's KV store for a specific task.
        *   **Inputs:** `task_id: str`, `key: str`, `value: any`.
        *   **Outputs:** `success: bool`.
    *   `hub_memory_read.pym`:
        *   **Functionality:** Allows a Sub-Agent to lazy-load its context programmatically via code execution, avoiding prompt bloat and context rotation on the base model side. 
        *   **Inputs:** `key: str` (e.g., `"task_intent"`, or `"architectural_constraints"`).
        *   **Outputs:** The JSON value stored by the Parent Agent in the Hub Daemon's memory bus.

---

## Applying this to the MVP Demo

If we use the **Recursive Environment Models (REM)** terminology for the MVP Demo, the pitch becomes overwhelmingly strong:

*"LLMs fail at massive codebases because of Context Rot. Standard tools try to fix this with Vector DBs. Remora fixes this with **Recursive Environment Models**. Watch as our Root Agent uses Python to grep a 100k-line Tree-sitter AST, and then dynamically compiles and launches isolated, LoRA-tuned **Micro-Environments** to execute targeted refactors in parallel, connected by a shared KV memory bus."*
