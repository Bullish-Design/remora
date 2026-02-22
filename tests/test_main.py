from __future__ import annotations

import runpy

from remora import cli


def test_main_invokes_cli(monkeypatch) -> None:
    called: list[bool] = []

    def fake_app() -> None:
        called.append(True)

    monkeypatch.setattr(cli, "app", fake_app)

    runpy.run_module("remora", run_name="__main__")

    assert called
