from __future__ import annotations

from .models import User


def parse_int(value: str, default: int = 0) -> int:
    try:
        return int(value)
    except ValueError:
        return default


def format_user(user: User) -> str:
    return f"{user.id}:{user.name}"


def chunk(items: list[str], size: int) -> list[list[str]]:
    buckets: list[list[str]] = []
    for index in range(0, len(items), size):
        buckets.append(items[index : index + size])
    return buckets
