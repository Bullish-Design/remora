# Implementation Guide: Step 10 - Indexer Service

## Target
Extract the file-watching/indexing logic into `remora/indexer/`, keep only a lightweight store + rules engine, and ensure the daemon publishes to the shared `NodeStateStore` for downstream consumers.

## Overview
- `indexer.daemon` watches work directories, runs the simplified discovery, and writes `NodeState` records (language, node type, file, last analyzed) into a fsdantic-based `NodeStateStore`.
- `indexer.rules` holds transformation logic for call graphs or dependency heuristics used by both the daemon and the dashboard.
- The daemon exposes a CLI entry point (`remora-index`) that spins up the watcher and optionally warms the store with a full scan.

## Steps
1. Create `remora/indexer/store.py` that defines `NodeState`/`FileIndex` (fsdantic `VersionedKVRecord`) and a `NodeStateStore` (TypedKVRepository) for persistent state.
2. Implement `indexer/daemon.py` that watches the configured paths, calls `discovery.discover()`, updates `NodeStateStore`, and emits events on the shared EventBus for new/updated nodes.
3. Move tree-sitter call graph helpers into `indexer/rules.py` and import them from both `indexer.daemon` and the dashboard to keep behavior synchronized.
4. Provide a lightweight CLI `remora-index` (e.g., in `indexer/cli.py`) that uses `remora.config.RemoraConfig` to start the watcher and optionally perform a single-run scan for verification.
