# CQRS Pattern Notes

## What is CQRS?

**Command Query Responsibility Segregation** is a pattern that separates read and write operations into different models.

## Key Concepts

### Commands

Commands are operations that **change state**:
- Create a record
- Update a record
- Delete a record

Commands should not return data (except for success/failure).

### Queries

Queries are operations that **read state**:
- Get a record by ID
- List all records
- Search records

Queries should not modify state.

## Why Use CQRS?

1. **Different scaling needs** - Reads often outnumber writes 10:1 or more
2. **Different optimization** - Writes need consistency, reads need speed
3. **Clearer code** - Each path has one job

## Implementation in This Project

In `src/processor.py`:

- `load_data()` is a **query** - reads from source
- `process_batch()` is a **command** - transforms and outputs

The DataProcessor follows CQRS principles by keeping these concerns separate.

## Event Sourcing

CQRS often pairs with **Event Sourcing**:

```
Command → Event → Event Store → Read Model
```

We don't use full event sourcing here, but the pattern is compatible.

## References

- Martin Fowler's CQRS article
- Greg Young's original CQRS documents
- See `docs/architecture.md` for how this fits our pipeline
