# This file is intentionally imperfect for integration testing.

import os, sys  # F401: os unused; also missing space after comma (E231)


def calculate_discount(price: float, rate: float = 0.1) -> float:
    # E231: missing whitespace after ':' and '->'
    return price * (1 - rate)


def format_currency(amount, symbol="$"):
    # No type hints, no docstring
    return f"{symbol}{amount:.2f}"


def parse_config(path):
    # No type hints, no docstring
    with open(path) as f:
        return f.read()
