"""Calculator module with intentional defects for testing."""

import os, sys  # F401: os unused, missing space after comma (E231)


def calculate_discount(price: float, rate: float = 0.1) -> float:
    # E231: missing whitespace after ':' and '->'
    # Missing docstring
    return price * (1 - rate)


def format_currency(amount, symbol="$"):
    # No type hints, no docstring
    # W291: trailing whitespace
    return f"{symbol}{amount:.2f} "


def parse_config(path):
    # No type hints, no docstring
    # Missing error handling
    with open(path) as f:
        return f.read()


def validate_email(email):
    """Validate email format."""
    # Has docstring but incomplete implementation
    if "@" not in email:
        return False
    return True


class Calculator:
    """Calculator class with basic operations."""

    def __init__(self, initial_value=0):
        # Missing type hints
        self.value = initial_value

    def add(self, x):
        # Missing type hints, missing docstring
        self.value += x
        return self.value

    def multiply(self, x):
        # Missing type hints, missing docstring
        self.value *= x
        return self.value
