# PLAN

## Critical Rule
NO SUBAGENTS: all work for this project is executed directly.

## Goal
Create an implementation-ready scaffold for a durable Tree-sitter node ID indexer using inline `graph:id` annotations.

## Steps
1. Create required project tracking docs in `.scratch/projects/treesitter-node-persistent-ids/`.
2. Create a template package layout under `template/` with clear module boundaries.
3. Add starter query files, SQLite schema, and CLI entrypoints.
4. Add starter tests for ID parsing and line indexing behavior.
5. Document architecture and usage so implementation can proceed with minimal redesign.

## Acceptance Criteria
1. `template/` contains a coherent package structure for parser/extractor/storage/pipeline layers.
2. Query placeholders and schema are present.
3. Starter tests and fixtures exist.
4. Tracking docs (`ASSUMPTIONS/PLAN/PROGRESS/CONTEXT/DECISIONS/ISSUES/REPO_RULES`) exist.

## Critical Rule
NO SUBAGENTS: all work for this project is executed directly.
