"""Minimal stario test stub for graph app tests.

Allows importing `remora_demo.web.graph.app` in environments where the
real Stario package is unavailable.
"""

from __future__ import annotations

import sys
import types


def install_stario_stub() -> None:
    """Install stub `stario` and `stario.html` modules once."""
    if "stario" in sys.modules and "stario.html" in sys.modules:
        return

    stario_mod = types.ModuleType("stario")
    html_mod = types.ModuleType("stario.html")

    class Context:  # pragma: no cover - marker type only
        pass

    class Writer:  # pragma: no cover - marker type only
        pass

    class Relay:
        def publish(self, _subject: str, _data: str) -> None:
            return None

        def subscribe(self, _pattern: str):
            async def _empty():
                if False:  # pragma: no cover
                    yield None

            return _empty()

    class RichTracer:
        pass

    class Stario:
        def __init__(self, _tracer: RichTracer) -> None:
            self.routes: list[tuple[str, str, object]] = []

        def get(self, path: str, handler: object) -> None:
            self.routes.append(("GET", path, handler))

        def post(self, path: str, handler: object) -> None:
            self.routes.append(("POST", path, handler))

    class SafeString(str):
        pass

    stario_mod.Context = Context
    stario_mod.Writer = Writer
    stario_mod.Relay = Relay
    stario_mod.RichTracer = RichTracer
    stario_mod.Stario = Stario
    html_mod.SafeString = SafeString

    sys.modules["stario"] = stario_mod
    sys.modules["stario.html"] = html_mod
