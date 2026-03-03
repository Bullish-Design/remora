"""Tests for the data processor module."""

import pytest
from src.processor import DataProcessor, DataRecord, calculate_statistics


class TestDataProcessor:
    """Test suite for DataProcessor class."""

    def test_load_data_returns_records(self):
        """Load data should return a list of DataRecord objects."""
        processor = DataProcessor()
        records = processor.load_data("dummy_source")

        assert len(records) > 0
        assert all(isinstance(r, DataRecord) for r in records)

    def test_validate_record_passes_by_default(self):
        """With no validators, all records should pass."""
        processor = DataProcessor()
        record = DataRecord(id="1", name="test", value=10.0)

        assert processor.validate_record(record) is True

    def test_validate_record_with_custom_validator(self):
        """Custom validators should be applied."""
        processor = DataProcessor()

        # Add a validator that rejects negative values
        processor.add_validator(lambda r: r.value >= 0)

        valid_record = DataRecord(id="1", name="test", value=10.0)
        invalid_record = DataRecord(id="2", name="test", value=-5.0)

        assert processor.validate_record(valid_record) is True
        assert processor.validate_record(invalid_record) is False

    def test_transform_record_applies_transforms(self):
        """Transforms should be applied in order."""
        processor = DataProcessor()

        # Add a transform that doubles the value
        def double_value(record):
            return DataRecord(
                id=record.id,
                name=record.name,
                value=record.value * 2,
            )

        processor.add_transform(double_value)

        record = DataRecord(id="1", name="test", value=10.0)
        result = processor.transform_record(record)

        assert result.value == 20.0

    def test_process_batch_full_pipeline(self):
        """Process batch should validate and transform all records."""
        processor = DataProcessor()

        # Only accept values > 5
        processor.add_validator(lambda r: r.value > 5)

        # Double the value
        processor.add_transform(lambda r: DataRecord(id=r.id, name=r.name, value=r.value * 2))

        records = [
            DataRecord(id="1", name="a", value=10.0),  # passes, becomes 20
            DataRecord(id="2", name="b", value=3.0),  # fails validation
            DataRecord(id="3", name="c", value=15.0),  # passes, becomes 30
        ]

        results = processor.process_batch(records)

        assert len(results) == 2
        assert results[0].value == 20.0
        assert results[1].value == 30.0


class TestCalculateStatistics:
    """Tests for the calculate_statistics function."""

    def test_empty_list(self):
        """Empty list should return zeros."""
        stats = calculate_statistics([])

        assert stats["count"] == 0
        assert stats["sum"] == 0.0

    def test_single_record(self):
        """Single record should calculate correctly."""
        records = [DataRecord(id="1", name="test", value=10.0)]
        stats = calculate_statistics(records)

        assert stats["count"] == 1
        assert stats["sum"] == 10.0
        assert stats["mean"] == 10.0
        assert stats["min"] == 10.0
        assert stats["max"] == 10.0

    def test_multiple_records(self):
        """Multiple records should calculate correctly."""
        records = [
            DataRecord(id="1", name="a", value=10.0),
            DataRecord(id="2", name="b", value=20.0),
            DataRecord(id="3", name="c", value=30.0),
        ]
        stats = calculate_statistics(records)

        assert stats["count"] == 3
        assert stats["sum"] == 60.0
        assert stats["mean"] == 20.0
        assert stats["min"] == 10.0
        assert stats["max"] == 30.0
