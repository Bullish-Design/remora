# Cairn Integration Test Coverage Report

This report tracks coverage for the Cairn integration suite.

## How to Generate

Run:

```bash
pytest tests/integration/cairn/ -v -m cairn --cov=remora.cairn_bridge --cov=remora.workspace --cov-report=term-missing
```

## Latest Results

- Date: TBD
- Command: `pytest tests/integration/cairn/ -v -m cairn --cov=remora.cairn_bridge --cov=remora.workspace --cov-report=term-missing`
- Notes: Run locally or in CI to populate coverage metrics.
