"""Demo Calculator for AST Summary testing."""


class Calculator:
    """A simple calculator class for demo purposes."""

    def __init__(self) -> None:
        self.value = 0

    def add(self, x: int, y: int) -> int:
        """Add two numbers together."""
        return x + y

    def subtract(self, x: int, y: int) -> int:
        """Subtract y from x."""
        return x - y

    def multiply(self, x: int, y: int) -> int:
        """Multiply two numbers."""
        return x * y

    def divide(self, x: int, y: int) -> float:
        """Divide x by y."""
        if y == 0:
            raise ValueError("Cannot divide by zero")
        return x / y


def main() -> None:
    """Main entry point."""
    calc = Calculator()
    result = calc.add(5, 3)
    print(f"5 + 3 = {result}")


if __name__ == "__main__":
    main()
