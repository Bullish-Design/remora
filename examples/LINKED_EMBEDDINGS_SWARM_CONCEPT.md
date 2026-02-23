# Linked Embeddings Swarm Concept

> **Status**: Concept / Design Draft
> **Related**: RECURSIVE_ENVIRONMENT_MODELS.md, COMPREHENSIVE_EMBEDDINGS_MODEL_SUITE.md

## 1. Overview

The **Linked Embeddings Swarm Concept** reimagines the codebase as a multidimensional vector space rather than a flat string of text or a simple AST graph. Each primary Tree-sitter node (functions, classes, modules) is embedded simultaneously across multiple distinct embedding spaces representing different facets of the code. 

By combining this with the **Recursive Environment Models (REM)** architecture, we deploy a swarm of specialized agents—each equipped with specific LoRA adapters and tools. These agents navigate the codebase by jumping between embedding spaces, querying high-quality reference libraries to find patterns, and recursively creating and refining task lists in a sandboxed environment until the user's ultimate goal is met.

## 2. The Multidimensional Node Embedding Strategy

Instead of a single massive embedding for a file or a chunk, every significant AST node is processed into a **Linked Node Entity** with pointers to separate vector spaces.

### The Embedding Spaces
1.  **Semantic/Docstring Space**: Contains the natural language explanation, comments, and docstrings of the node.
    *   *Agent Query*: "Find the node that handles rate-limiting middleware."
2.  **Structural/Code Space**: Contains the raw logic and syntax, stripped of comments.
    *   *Agent Query*: "Find nodes that use a `dict` comprehension to filter responses."
3.  **Relational/Graph Space**: Embeddings that encode the Tree-sitter AST relationships (caller/callee, parent/child, interfaces).
    *   *Agent Query*: "Find all nodes that invoke the `get_db_session` utility."

Furthermore, **Golden Reference Libraries** (e.g., high-quality open-source projects or company standards) are pre-embedded in the exact same multidimensional format to act as a searchable knowledge base.

## 3. The Specialized Agent Swarm

Agents are specialized via vLLM-served LoRA adapters depending on the dimension they excel in navigating.

### The Architect (Graph & Semantic Navigator)
*   **Role**: Breaks down the initial prompt, queries semantic and graph spaces to map out the "blast radius" of the request.
*   **Action**: Creates the initial `task.md` in the Cairn KV memory bus.

### The Implementer (Code & Pattern Matcher)
*   **Role**: Executes the specific coding tasks.
*   **Action**: Uses programmatic REPL tools to query the *Code Space* of the target repository *and* the Golden Reference Libraries simultaneously. "How did the Golden Library implement this exact AST structure?"

### The Verifier (Test Gen & Validation)
*   **Role**: Queries the codebase's existing tests in the Semantic space to understand testing conventions, then writes tests for the Implementer's changes.

## 4. The Recursive Execution Loop

Agents don't just prompt-stuff the embeddings; they act recursively inside a Grail sandbox.

1.  **Task Ingestion**: The Architect receives a goal (e.g., "Implement JWT auth") and creates a `task.md` file in the Cairn KV memory bus. It queries the Semantic Space for "auth" and identifies 3 relevant nodes.
2.  **Context Iteration (The RLM Pattern)**:
    *   The Architect operates within its sandboxed Cairn Workspace. It uses tools to perform cross-space searches and writes the results to context files in the workspace: 
        ```python
        # Agent's generated search query via tools
        semantic_hits = vector_db.search("semantic", query="user authentication", top_k=5)
        graph_dependencies = vector_db.search("graph", query=semantic_hits[0].node_id)
        ```
    *   It refines its understanding by aggregating context across dimensions and analyzing the physical files generated in its workspace, providing physical evidence of its thought process.
3.  **Task Refinement & Creation**:
    *   Discovering that a password hashing utility is missing, the Architect updates the `task.md` in the Cairn KV to add: `[ ] Create hashing utility`.
    *   It recursively spawns an Implementer agent for this new sub-task, passing the localized context and provisioning a child Cairn Workspace.
4.  **Reference Implementation**:
    *   The Implementer searches the Code Space of a *Golden Reference Library* (e.g., FastAPI's security utils) to retrieve an idiomatic, highly-rated implementation of password hashing.
    *   The Implementer creates the new file (`security.py`) directly within its Cairn Workspace, writes the code, and marks the sub-task as complete `[x]`.

## 5. Connection to Existing LLM Research

The concept of representing code as "Linked Node Entities" across multidimensional spaces strongly aligns with current advancements in **Code Representation Learning**. 

*   **Code Property Graphs (CPGs)**: The idea of merging ASTs (Structural/Code Space) with semantic relationships (Control Flow and Data Flow) is well-established in research as Code Property Graphs. The Linked Embeddings approach takes this a step further by explicitly storing these facets in distinct, queryable vector spaces for agentic navigation.
*   **Graph Neural Networks (GNNs)**: Current research utilizes GNNs to learn "structure-aware node embeddings"—dense vectors that capture both the properties of individual code nodes and their relational edges within the AST or CPG.
*   **Tree-based Positional Embeddings**: Models are increasingly moving away from linear token sequences, using Tree-sitter ASTs to explicitly encode hierarchical relationships (like nested loops or depth) into the multidimensional embeddings.

Remora's approach operationalizes this research, moving it from static analysis into an interactive, agentic environment.

## 6. Why This is the Ultimate MVP Demo

This concept bridges the best aspects of your existing research into a unified, highly visual demo.

*   **From `RECURSIVE_ENVIRONMENT_MODELS.md`**: The agents use their Cairn Workspaces to algorithmically query distinct vector databases to refine their context before acting, leaving a physical trail of evidence (context files, drafts) in the workspace.
*   **From `COMPREHENSIVE_EMBEDDINGS_MODEL_SUITE.md`**: We showcase FunctionGemma orchestrating the searches and EmbeddingGemma (with MRL) enabling ultra-fast, multi-space retrieval.
*   **From `MVP_DEMO_CONCEPT.md`**: The dashboard visualizes agents updating a living, breathing markdown task list while dynamically swapping LoRA adapters based on which embedding space they are currently navigating. 

### The Demo "Wow" Factor
Watch as an agent:
1.  **Explores**: Queries the Semantic Space of your repo to find roughly where a feature should go.
2.  **Learns**: Queries the Graph Space of a famous OSS repo to see how they structured the same feature.
3.  **Plans**: Automatically writes a multi-step `task.md` in the KV store, backed by physical research artifacts in its workspace.
4.  **Executes**: Spawns sub-agents that write files, run tests, and check off their own tasks organically until the feature is built.
