"""Demo harness for Companion — scripted scenarios with A4-sized terminal rendering."""

from remora_demo.companion.demo.harness import DemoConfig, DemoHarness
from remora_demo.companion.demo.recording import AsciicastWriter
from remora_demo.companion.demo.renderer import RenderConfig, TerminalRenderer
from remora_demo.companion.demo.scenarios import DemoScenario, DemoStep

__all__ = [
    "AsciicastWriter",
    "DemoConfig",
    "DemoHarness",
    "DemoScenario",
    "DemoStep",
    "RenderConfig",
    "TerminalRenderer",
]
