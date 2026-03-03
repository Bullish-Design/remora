"""Data processing module for the example project.

This module handles loading, transforming, and validating data from various sources.
The CQRS pattern is used for separating read and write operations.
"""

from dataclasses import dataclass
from typing import Any


@dataclass
class DataRecord:
    """A single record from the data source."""

    id: str
    name: str
    value: float
    metadata: dict[str, Any] | None = None


class DataProcessor:
    """Processes data records with validation and transformation.

    This class implements the core data processing pipeline:
    1. Load raw data from source
    2. Validate against schema
    3. Transform to canonical format
    4. Output to destination

    See docs/architecture.md for the full pipeline diagram.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialize the processor with optional configuration.

        Args:
            config: Configuration dictionary with keys:
                - strict_validation: bool - fail on first error
                - transform_functions: list - custom transforms
                - output_format: str - "json" | "csv" | "parquet"
        """
        self.config = config or {}
        self._validators: list[callable] = []
        self._transforms: list[callable] = []

    def load_data(self, source: str) -> list[DataRecord]:
        """Load data from a source path or URL.

        Args:
            source: Path to data file or URL

        Returns:
            List of DataRecord objects

        Raises:
            FileNotFoundError: If source doesn't exist
            ValidationError: If data fails schema validation
        """
        # Simulated data loading
        records = []

        # In real implementation, would read from file
        sample_data = [
            {"id": "1", "name": "alpha", "value": 10.5},
            {"id": "2", "name": "beta", "value": 20.3},
            {"id": "3", "name": "gamma", "value": 30.1},
        ]

        for item in sample_data:
            record = DataRecord(
                id=item["id"],
                name=item["name"],
                value=item["value"],
            )
            records.append(record)

        return records

    def validate_record(self, record: DataRecord) -> bool:
        """Validate a single record against all registered validators.

        Args:
            record: The record to validate

        Returns:
            True if all validations pass

        Note:
            Custom validators can be registered via add_validator()
        """
        for validator in self._validators:
            if not validator(record):
                return False
        return True

    def transform_record(self, record: DataRecord) -> DataRecord:
        """Apply all registered transforms to a record.

        Transforms are applied in registration order.
        Each transform receives the output of the previous one.
        """
        result = record
        for transform in self._transforms:
            result = transform(result)
        return result

    def process_batch(self, records: list[DataRecord]) -> list[DataRecord]:
        """Process a batch of records through the full pipeline.

        This is the main entry point for batch processing.

        Args:
            records: List of records to process

        Returns:
            List of validated and transformed records
        """
        results = []

        for record in records:
            if self.validate_record(record):
                transformed = self.transform_record(record)
                results.append(transformed)

        return results

    def add_validator(self, validator: callable) -> None:
        """Register a custom validation function.

        Args:
            validator: Function that takes a DataRecord and returns bool
        """
        self._validators.append(validator)

    def add_transform(self, transform: callable) -> None:
        """Register a custom transformation function.

        Args:
            transform: Function that takes and returns a DataRecord
        """
        self._transforms.append(transform)


def calculate_statistics(records: list[DataRecord]) -> dict[str, float]:
    """Calculate basic statistics from a list of records.

    Returns:
        Dictionary with 'count', 'sum', 'mean', 'min', 'max'
    """
    if not records:
        return {"count": 0, "sum": 0.0, "mean": 0.0, "min": 0.0, "max": 0.0}

    values = [r.value for r in records]

    return {
        "count": len(values),
        "sum": sum(values),
        "mean": sum(values) / len(values),
        "min": min(values),
        "max": max(values),
    }
