# This file is intentionally imperfect for integration testing.

import os, sys  # F401: os and sys unused


def calculate_discount(price: float, rate: float = 0.1) -> float:
    # F841: unused variable
    unused = rate
    return price * (1 - rate)


def format_currency(amount, symbol="$"):
    # No type hints, no docstring.
    return f"{symbol}{amount:.2f}"


def parse_config(path):
    # No type hints, no docstring
    with open(path) as f:
        return f.read()
