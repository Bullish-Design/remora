# DEV GUIDE STEP 2: Configuration System

## Goal
Define the Remora configuration schema and loader with CLI overrides.

## Why This Matters
Config drives which files are processed, which agents run, and how Cairn is tuned.

## Implementation Checklist
- Implement `RemoraConfig` and sub-configs using Pydantic.
- Add YAML loader that reads `remora.yaml` or `--config` path.
- Merge CLI options on top of file defaults (CLI wins).
- Validate config and raise structured errors.

## Suggested File Targets
- `remora/config.py`
- `remora/errors.py` for config error codes

## Implementation Notes
- Follow the schema in `SPEC.md` section 3.
- Map schema validation failures to exit code `3` and codes `CONFIG_00x`.
- Provide a `remora config` command to print merged config.

## Testing Overview
- **Unit test:** YAML parsing and validation success.
- **Unit test:** Invalid YAML returns `CONFIG_002` and exit code `3`.
- **Unit test:** Invalid schema returns `CONFIG_003` and exit code `3`.
- **Integration test:** `remora config -f yaml` prints merged defaults.
