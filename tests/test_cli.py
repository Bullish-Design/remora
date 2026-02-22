from __future__ import annotations

import sys
from types import SimpleNamespace

from typer.testing import CliRunner

import remora.cli as cli
from remora.cli import app, _exit_code, _fetch_models
from remora.config import OperationConfig, RemoraConfig


def test_config_command_outputs_yaml() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["config", "--format", "yaml"])
    assert result.exit_code == 0
    assert "agents_dir" in result.output


def test_exit_code_variants() -> None:
    assert _exit_code(None) == 2
    assert _exit_code(SimpleNamespace(failed_operations=0, successful_operations=1)) == 0
    assert _exit_code(SimpleNamespace(failed_operations=1, successful_operations=0)) == 2
    assert _exit_code(SimpleNamespace(failed_operations=2, successful_operations=1)) == 1


def test_fetch_models_returns_ids(monkeypatch) -> None:
    class FakeModels:
        def list(self):
            return SimpleNamespace(data=[SimpleNamespace(id="alpha"), SimpleNamespace(id="beta")])

    class FakeClient:
        def __init__(self, **_kwargs):
            self.models = FakeModels()

    fake_module = SimpleNamespace(OpenAI=FakeClient)
    monkeypatch.setitem(sys.modules, "openai", fake_module)

    models = _fetch_models(SimpleNamespace(base_url="http://example", api_key="token", timeout=1))

    assert models == {"alpha", "beta"}


def test_list_agents_outputs_table(monkeypatch, tmp_path) -> None:
    config = RemoraConfig()
    config.agents_dir = tmp_path / "agents"
    config.agents_dir.mkdir()
    config.server.default_adapter = "demo"
    config.operations = {"lint": OperationConfig(subagent="lint.yaml")}
    (config.agents_dir / "lint.yaml").write_text("name: lint", encoding="utf-8")

    fake_definition = SimpleNamespace(grail_summary={"valid": True, "warnings": []})

    monkeypatch.setattr(cli, "load_config", lambda *_args, **_kwargs: config)
    monkeypatch.setattr(cli, "_fetch_models", lambda *_args, **_kwargs: {"demo"})
    monkeypatch.setattr(cli, "load_subagent_definition", lambda *_args, **_kwargs: fake_definition)

    runner = CliRunner()
    result = runner.invoke(app, ["list-agents"])

    assert result.exit_code == 0
    assert "lint" in result.output
