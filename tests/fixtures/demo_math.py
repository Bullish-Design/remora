"""Demo module for integration testing."""


def add(x: int, y: int) -> int:
    """Add two numbers."""
    return x + y


def multiply(x: int, y: int) -> int:
    return x * y


def divide(x: float, y: float) -> float:
    if y == 0:
        raise ValueError("Cannot divide by zero")
    return x / y


class MathUtils:
    """Utility class for math operations."""

    def __init__(self, precision: int = 2):
        self.precision = precision

    def round_result(self, value: float) -> float:
        return round(value, self.precision)

    def calculate_percentage(self, value: float, total: float) -> float:
        if total == 0:
            return 0.0
        return self.round_result((value / total) * 100)
