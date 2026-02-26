# Implementation Guide: Step 3 - Configuration System

## Target
Implement the flattened `remora.yaml` + structured-agents bundle split so every component reads from the same frozen `RemoraConfig` while bundle-specific settings stay in `bundle.yaml` files.

## Overview
- `remora.yaml` defines discovery paths, bundle mappings, execution knobs (concurrency/error policy/timeout), indexer/dashboard endpoints, workspace cleanup rules, and default model server settings.
- `RemoraConfig` is a frozen dataclass constructed once at startup and passed into discovery, workspace, executor, and services; environment variables with `REMORA_` prefixes override values.
- Bundle metadata such as `node_types`, `priority`, and `requires_context` lives in Remora's own table rather than the structured-agents manifest so we can guide graph building without altering the bundle format.

## Contract Touchpoints
- `load_config()` consumes `remora.yaml`, applies `REMORA_*` overrides, and returns the shared `RemoraConfig` instance.
- Bundle metadata maps bundle names to `node_types`, `priority`, and `requires_context` without altering bundle manifests.
- `remora.example.yaml` mirrors the runtime schema for operators and tests.

## Done Criteria
- Configuration loads once, validates values, and is immutable after construction.
- Environment overrides apply consistently across all config sections.
- Tests cover loading, overrides, and default fallbacks.

## Steps
1. Replace `src/remora/config.py` with dataclasses for each config section plus `load_config()` that reads `remora.yaml`, applies `REMORA_*` overrides, validates values, and returns a frozen `RemoraConfig` instance.
2. Document the expected shape in `remora.example.yaml`, covering discovery paths, bundle directory/mapping, execution settings, indexer store, dashboard host/port, workspace TTL, and model base URL.
3. Update `src/remora/__init__.py` to export `RemoraConfig` and `load_config` and ensure every component pulls its slice from the same instance instead of global singletons.
4. Add `tests/test_config.py` to cover valid loading, environment overrides, immutability, and default fallbacks so the configuration layer stays honest.
