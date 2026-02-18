from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Greeter:
    name: str

    def greet(self, excitement: int = 1) -> str:
        message = f"Hello, {self.name}" + "!" * excitement
        return message


def greet_all(names: list[str]) -> list[str]:
    greeter = Greeter("friend")
    results = []
    for name in names:
        results.append(greeter.greet())
    return results
