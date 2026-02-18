from __future__ import annotations


def average(values: list[int]) -> float:
    total = sum(values)
    return total / len(values)


def normalize(values: list[int]) -> list[float]:
    mean = average(values)
    return [value - mean for value in values]
