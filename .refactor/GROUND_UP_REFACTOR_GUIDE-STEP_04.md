# Implementation Guide: Step 4 - Graph Topology

## Target
Create a pure-topology module that maps discovered `CSTNode`s to immutable `AgentNode`s and exposes the dependency DAG information needed by the executor.

## Overview
- `AgentNode` is a frozen dataclass (`id`, `name`, `target`, `bundle_path`, upstream/downstream sets) with no mutable state.
- `graph.build_graph()` accepts discovered nodes, the bundle metadata mapping, and optional dependency hints, returning the ordered list plus adjacency relationships.
- Graph metadata such as `priority`, `node_types`, and `requires_context` live in `BundleMetadata` records keyed by bundle name to keep manifest files untouched.

## Contract Touchpoints
- `graph.build_graph()` consumes discovered `CSTNode` data and bundle metadata to build the dependency DAG.
- `AgentNode.bundle_path` is the executor contract for locating bundles at runtime.
- Topology helpers (`topological_sort`, `group_by_priority`) feed executor scheduling decisions.

## Done Criteria
- Graph generation is deterministic and `AgentNode` objects remain immutable.
- Dependency edges reflect bundle metadata and discovery-derived relationships.
- Unit tests verify ordering, adjacency, and filtering behavior.

## Steps
1. Implement `graph.AgentNode` with the attributes above and helper properties for ready checks.
2. Build `graph.build_graph(nodes, bundle_metadata)` that filters nodes by `node_types`, creates nodes per bundle, computes upstream/downstream sets via simple dependency detection (imports, file adjacency), and returns the DAG.
3. Expose helper functions like `graph.topological_sort()` and `graph.group_by_priority()` to support the executor's concurrency decisions.
4. Write tests (`tests/unit/test_graph.py`) that feed sample `CSTNode` data and bundle metadata and assert the returned graph ordering and adjacency matches expectations.
