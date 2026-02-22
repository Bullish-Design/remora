# Concept: Tree-Sitter AST Driven Agent Swarm

This document explores a highly experimental, decentralized architecture for Remora, leveraging Tree-sitter's AST (Abstract Syntax Tree) representation as the operational graph for a swarm of fine-tuned micro-agents.

## Core Vision

Instead of using a monolithic LLM to process an entire file or chunk of code, the system decomposes the codebase into its constituent Tree-sitter nodes. **Every distinct type of AST node (e.g., `class_definition`, `function_definition`, `for_statement`, `expression`) is managed by its own specialized, fine-tuned "tiny" reasoning model paired with a FunctionGemma model for tool calling.**

These models operate collaboratively across the codebase graph, negotiating changes and passing context to their node neighbors up and down the syntax tree.

## System Architecture

### 1. The Multi-Modal Node Embeddings
Each node within the AST is embedded across multiple linked vector spaces, representing different conceptual dimensions:
* **Syntax (Code):** The literal source code text of the node.
* **Semantics (Comments):** Summaries and docstrings associated with or generated for the node.
* **Types / Signatures:** The structural inputs and outputs matching the node.
* **Topology (Graph):** Its structural relationship to other nodes (parent, children, siblings, data flow).

### 2. The Granular Agent Pair (The "Node Agent")
For any given node, its assigned intelligence consists of:
*   **A Fine-Tuned Reasoning Model:** Trained specifically to understand and manipulate that exact structural concept (e.g., a "Function Definition Expert").
*   **A FunctionGemma Model:** Trained for accurate tool execution, armed with advanced Grail mathematical scripts.
*   **Sandbox Access:** A dedicated `Cairn` KV sandbox instance isolating the agent's work.
*   **Grail Tools:** Access to `.pym` and `.py` scripts for running actual codebase capabilities.
*   **Local State:** Access to the codebase embeddings and its targeted multi-vector search space.

### 3. IDE / Neovim Integration
The entry point is a deeply integrated developer tool (e.g., a Neovim plugin):
1. The developer uses Tree-sitter object selection (e.g., `vif` to select inner function, or `vac` for class) to highlight a specific syntactic subgraph.
2. The user describes the requested change (e.g., "Refactor this to use the Cairn KV store instead of local dicts").

## Cross-Sectional Capabilities: Compiler Mathematics

Because the architecture embeds the AST across four dimensions, the Swarm transitions from a standard LLM agent framework into an engine capable of advanced compiler mathematics. The FunctionGemma models are equipped with Grail scripts (`.pym`) that execute classical graph theory, linear algebra, and vector calculus algorithms against the codebase.

### 1. Vector Space Mathematics (Cross-Modal Search & Arithmetic)
By aligning the embedding spaces, agents can perform semantic arithmetic to isolate specific nodes or divine intent.
* **Cross-Modal Retrieval Projection:** An agent takes a semantic query ("handles user authentication") and projects it into the Topological space to find the *shape* of authentication (e.g., a function wrapping a database call returning a boolean).
* **Concept Arithmetic (Latent Space Algebra):** The ability to do math on code concepts. For example: `Vector("def execute(task)") - Vector("local execution") + Vector("remote API call") = Vector(Desired Final State)`. A `vector_arithmetic.pym` script takes node embeddings, adds/subtracts context vectors, and queries the database for the closest resulting structural match to use as an implementation template.

### 2. Graph Theory & Network Analysis (Topological Navigation)
The AST is a Directed Acyclic Graph (DAG), but data flow and function calls turn it into a complex cyclic network. Agents use these algorithms to navigate and analyze the network:
* **PageRank (Code Importance Scoring):** Instead of ranking web pages, the system ranks AST nodes by their "Incoming Data Flow" and "Call Frequency." A utility function called by 50 other functions has a massive PageRank. If a user asks to "optimize the codebase," the Supervisor LoRA runs PageRank, identifies the critical choke-point nodes, and assigns agents specifically to those high-value targets.
* **Dijkstra's or A* Search (Data Flow Pathfinding):** Finding the semantic path between two AST nodes. If a developer highlights a UI button and says "make this button save to the cloud," the agent uses A* to pathfind the data flow from the UI node to the Database node, identifying exactly which intermediate `controller` and `service` nodes need to be assigned sub-agents to bridge the gap.
* **Graph Partitioning / Community Detection (Louvain Method):** Detecting clusters of tightly coupled nodes that form a "feature" or "domain" (e.g., all nodes related to 'billing'). A Domain Agent uses this to suggest where to split a monolithic file into smaller, decoupled microservices.

### 3. Matrix Transformations (Structural Refactoring)
Transforming the AST is modeled as matrix operations representing the graph adjacency matrix.
* **Isomorphism Checking (Pattern Matching):** Checking if two subgraphs (matrices) are structurally identical, regardless of variable names. A Refactoring Agent uses an `isomorphism.pym` script to scan the codebase for subgraphs that match known anti-patterns (nested loops that could be comprehensions) or to entirely deduplicate logic across the repo.
* **AST Matrix Multiplication (Dependency Resolution):** If Matrix $A$ represents "Function Calls" and Matrix $B$ represents "Variable Dependencies", computing $AB$ reveals indirect dependencies. A `dependency_matrix_calc.pym` script allows an agent to instantly calculate the "blast radius" of changing a specific parameter without having to manually read through downstream files.

### 4. Continuous Probability & Manifold Learning
When an agent needs to understand a massive, complex file or make bets on changes:
* **UMAP / t-SNE (Codebase Cartography):** Reducing the 1536-dimensional node embeddings down to 2D/3D space while preserving local relationships. The Supervisor uses this to cluster the entire codebase. When building a new feature, it looks at the manifold to see where similar concepts "live" and decides which existing module the new code should be injected into.
* **Markov Random Fields / Bayesian Infection Propagation:** Modeling probability across the AST. If Node A is modified and has a 20% chance of throwing a new Exception, how does that probability propagate through the graph to Node Z? The Test Generation Agent uses this mathematical model to determine *exactly* which edge cases to test. Instead of random unit tests, it generates tests for the nodes with the highest mathematical probability of state corruption.

## Execution Workflow: The "Fan-Out" Graph Swarm

When a user initiates a request, the system triggers a decentralized "Swarm" workflow:

1. **Intent Decoding (The Supervisor LoRA):**
   * The user's natural language request and the highlighted AST nodes are passed to a dynamic Supervisor LoRA.
   * This LoRA deciphers the intent, researches the implications across the linked embedding spaces using Graph Partitioning, and creates a master Plan.
   * It defines the **Final Desired State** of the codebase graph.

2. **Test-Driven Initialization:**
   * Before any code is changed, specialized agent pairs are spun up to calculate Bayesian Infection probabilities and generate unit tests defining the successful completion of the Final Desired State.

3. **Graph Subcontracting (Fan-Out Execution):**
   * The Supervisor hands the entrypoint Task to the Agent responsible for the top-level highlighted node.
   * **Down-leveling:** If the top-level Agent (e.g., a Class Agent) needs its internal functions modified, it "subcontracts" those tasks to the specific Function Agents responsible for its child nodes.
   * **Lateral Negotiation:** If a Function Agent realizes it needs a new utility, it can request its sibling nodes, or use A* Pathfinding to traverse the Graph Embedding space and request changes from completely different files/nodes.
   * **Upstream Resolution:** Once child nodes complete their sandboxed generation and tests pass, they pass the finalized state back up to their parent nodes for integration.

## Handling the Concurrency: vLLM Batched Inference
A critical enabler of this architecture is the backend inference engine. Using `vLLM` with batched inference and dynamically loaded on-demand LoRA adapters allows this to scale efficiently.
* We can run 10+ "tiny" fine-tuned logic models concurrently.
* We will not swamp the VRAM and will not suffer severe model loading overhead.
* The system relies on continuous concurrent batched inference throughput, seamlessly swapping adapters as the swarm processes different nodes.

## Dataset Generation Strategy

To train the dozens/hundreds of specific "Node Agents" and the multi-vector embeddings, a massive autonomous data generation pipeline is required:
1. **Source Material:** Curate a list of top-tier, canonical Python repositories known for exceptional code quality, consistent docstrings, and robust patterns.
2. **Teacher Model (Large LLM) Annotation:**
   * A highly capable LLM traverses the source ASTs using Tree-sitter.
   * For *every node*, it generates extensive metadata: descriptive summaries, edge-case analysis, structural graph data, and inferred types.
   * It executes the code where possible, capturing runtime state, inputs, and outputs to inject into the semantic vector space.
3. **Dataset Splitting:** This rich metadata is partitioned. The code text goes to the Syntax dataset, summaries to the Semantic dataset, structure to the Topological dataset. 
4. **LoRA/Model Fine-tuning:** We train the "Tiny" reasoning models exclusively on these tightly scoped slices—yielding models that are incredibly cheap to run, but possess genius-level intuition for a very specific AST structural pattern.
