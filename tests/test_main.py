from __future__ import annotations

import runpy

from remora import cli


def test_main_invokes_cli(monkeypatch) -> None:
    called: list[bool] = []

    def fake_main() -> None:
        called.append(True)

    monkeypatch.setattr(cli, "main", fake_main)

    runpy.run_module("remora", run_name="__main__")

    assert called
