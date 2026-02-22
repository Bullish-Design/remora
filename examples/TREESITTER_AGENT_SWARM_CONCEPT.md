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
*   **A FunctionGemma Model:** Trained for accurate tool execution.
*   **Sandbox Access:** A dedicated `Cairn` KV sandbox instance isolating the agent's work.
*   **Grail Tools:** Access to `.pym` and `.py` scripts for running actual codebase capabilities.
*   **Local State:** Access to the codebase embeddings and its targeted multi-vector search space.

### 3. IDE / Neovim Integration
The entry point is a deeply integrated developer tool (e.g., a Neovim plugin):
1. The developer uses Tree-sitter object selection (e.g., `vif` to select inner function, or `vac` for class) to highlight a specific syntactic subgraph.
2. The user describes the requested change (e.g., "Refactor this to use the Cairn KV store instead of local dicts").

## Execution Workflow: The "Fan-Out" Graph Swarm

When a user initiates a request, the system triggers a decentralized "Swarm" workflow:

1. **Intent Decoding (The Supervisor LoRA):**
   * The user's natural language request and the highlighted AST nodes are passed to a dynamic Supervisor LoRA.
   * This LoRA deciphers the intent, researches the implications across the linked embedding spaces, and creates a master Plan.
   * It defines the **Final Desired State** of the codebase graph.

2. **Test-Driven Initialization:**
   * Before any code is changed, specialized agent pairs are spun up to formulate and generate unit tests defining the successful completion of the Final Desired State.

3. **Graph Subcontracting (Fan-Out Execution):**
   * The Supervisor hands the entrypoint Task to the Agent responsible for the top-level highlighted node.
   * **Down-leveling:** If the top-level Agent (e.g., a Class Agent) needs its internal functions modified, it "subcontracts" those tasks to the specific Function Agents responsible for its child nodes.
   * **Lateral Negotiation:** If a Function Agent realizes it needs a new utility, it can request its sibling nodes, or traverse the Graph Embedding space to request changes from completely different files/nodes.
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
