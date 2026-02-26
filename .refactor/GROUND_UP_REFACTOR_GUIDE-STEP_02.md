# Implementation Guide: Step 2 - Cairn Workspace and Data Provider

## Target
Replace the legacy workspace abstractions with Cairn-based isolation and wrap the virtual filesystem lifecycle so Grail tools see the right files and downstream agents only observe accepted changes.

## Overview
- `remora.yaml` declares the Cairn base path, workspace cleanup TTL, and snapshot storage location consumed by the workspace manager.
- `CairnDataProvider` reads the target `CSTNode` and related files from the overlay before each Grail tool load so the `files` dict is ready for execution.
- `CairnResultHandler` interprets pure-function tool outputs and writes files (and metadata) back into the agent's overlay layer, leaving the shared base untouched until acceptance.

## Contract Touchpoints
- `CairnDataProvider.load_files()` assembles the `files` dict passed to `grail.GrailScript.run(files=...)`.
- Workspace creation reads `remora.yaml` for the base path, cleanup TTL, and snapshot storage location.
- `CairnResultHandler.handle()` persists updates and metadata via `workspace.write()`.

## Done Criteria
- Workspaces are created per agent run, snapshot on checkpoints, and expire based on TTL.
- Grail tools run with overlay-backed `files` dict populated per node.
- Result handling persists structured outputs without mutating the shared base.

## Steps
1. Implement `remora.workspace.CairnWorkspaceManager` that can create workspaces per agent run, snapshot them when checkpoints occur, and expire them based on TTL.
2. Implement `CairnDataProvider.load_files(node)` to gather the target file, shared configs, and any context-required neighbors, returning the dict passed to `grail.GrailScript.run(files=...)`.
3. Implement `CairnResultHandler.handle(result)` to persist structured outputs (updated files, diagnostics, metadata) via `workspace.write()` and update any workspace-level status for downstream agents.
4. Wire workspace creation into `executor.GraphExecutor.run()`, ensuring each ready node receives a fresh workspace overlay that merges with the base on acceptance and snapshots before checkpoints.
