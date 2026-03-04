# Data Processing Architecture

This document describes the architecture of our data processing pipeline.

## Overview

The data processing system follows a **pipeline pattern** with distinct stages:

1. **Ingestion** - Load raw data from sources
2. **Validation** - Verify data meets schema requirements  
3. **Transformation** - Convert to canonical format
4. **Output** - Write to destination

## Core Components

### DataProcessor

The `DataProcessor` class in `src/processor.py` is the main orchestrator. It:

- Manages validators and transforms
- Coordinates batch processing
- Handles error recovery

See the implementation for details on the `process_batch()` method.

### DataRecord

A dataclass representing a single record:

```python
@dataclass
class DataRecord:
    id: str
    name: str
    value: float
    metadata: dict[str, Any] | None = None
```

## CQRS Pattern

We use **Command Query Responsibility Segregation** (CQRS) to separate:

- **Commands** - Write operations that modify state
- **Queries** - Read operations that return data

This allows us to optimize each path independently.

### Benefits

1. **Scalability** - Read and write paths scale independently
2. **Performance** - Queries can use denormalized views
3. **Simplicity** - Each side has a clear responsibility

### Implementation Notes

The `DataProcessor.load_data()` method is a query operation.
The `DataProcessor.process_batch()` method is a command that produces output.

## Pipeline Diagram

```
┌──────────┐    ┌──────────┐    ┌───────────┐    ┌────────┐
│  Source  │───▶│  Loader  │───▶│ Validator │───▶│ Output │
└──────────┘    └──────────┘    └───────────┘    └────────┘
                     │                │
                     ▼                ▼
               DataRecord        Transforms
```

## Configuration

The processor accepts a config dictionary:

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| strict_validation | bool | false | Fail on first error |
| transform_functions | list | [] | Custom transforms |
| output_format | str | "json" | Output format |

## Statistics

Use `calculate_statistics()` for basic metrics:

- count
- sum
- mean
- min
- max

## Related

- See `tests/test_processor.py` for usage examples
- See `src/processor.py` for implementation details
