# examples/treesitter_swarm/README.md
# Tree-Sitter AST Driven Agent Swarm

This directory contains a conceptual modeling of the `TreeSitter Swarm` architecture. The intent of this architecture is to map the Tree-sitter AST natively to fine-tuned micro-agents. 

## Object-Oriented Mock Implementation
Following a "true OOP" structural design, the concept is broken down into small, encapsulated models using Pydantic:

* `models/node.py`: Defines the `TreeSitterNode` and `NodeEmbeddingSpace`.
* `models/task.py`: Defines the strictly hierarchical `SwarmTask` tracking system.
* `models/agent.py`: Pairs a functional logic model with the structural reasoning model in `NodeAgent`.
* `core/swarm.py`: Defines the `SupervisorLoRA` entrypoint and the `AgentSwarm` graph orchestrator.

## Architectural Critique and Refactoring Suggestions

While the decentralized AST-agent approach provides unparalleled isolation of context, there are significant architectural flaws and bottlenecks in the defined mechanism that should be noted:

### 1. The "Telephone Game" Context Loss
**The Flaw:** By forcing nodes to only communicate upstream/downstream with immediate AST parents and children, you risk severe context degradation. A `return_statement` agent might not fully understand the intent passed down from the `class_definition` agent 4 levels up.
**Refactor Opportunity:** Introduce a "Shared Swarm Memory Bus" (potentially using the Cairn KV store globally for the task) where any node agent can instantly lookup the original `SwarmTask` intent without relying on its parent to explain it properly. This increases cohesion without violating the structural encapsulation.

### 2. VRAM and Context Switching Overhead
**The Flaw:** Spinning up a uniquely fine-tuned LoRA for *every single node type* (e.g., `tiny-for-loop-expert`, `tiny-binary-operator-expert`) will cause massive VRAM chunking or constant disk-swapping in vLLM. The overhead of model-switching will dominate the actual inference time, reducing throughput to a crawl during fan-out.
**Refactor Opportunity:** Group structural concepts into slightly broader domain models (e.g., `tiny-control-flow-expert`, `tiny-declaration-expert`) rather than per-node. This reduces the number of LoRA adapters loaded while still maintaining highly specific expertise.

### 3. Asymmetric Dataset Generation
**The Flaw:** Generating exhaustive summary and topological data for generic leaf nodes like literal strings or simple assignments is mostly noise and pollutes the semantic vector space, making graph search wildly inefficient. 
**Refactor Opportunity:** Restrict the multi-modal embeddings and agent-pairing to "Meaningful Structural Nodes" (e.g., Classes, Functions, complex List Comprehensions, Decorators) while treating raw expressions/leaf nodes as simple text properties of those larger structures.

## Next Steps
To prototype this, the focus should be on building the `SupervisorLoRA` intent parser and ensuring the multi-vector search (Syntax, Semantic, Type, Topology) retrieves the correct sub-graph effectively before relying on downstream agents.
