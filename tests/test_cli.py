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
    config_file = tmp_path / "remora.yaml"
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()

    config_content = f"""
agents_dir: "{agents_dir.resolve().as_posix()}"
server:
  default_adapter: "demo"
operations:
  lint:
    enabled: true
    subagent: "lint.yaml"
"""
    config_file.write_text(config_content, encoding="utf-8")

    lint_agent = agents_dir / "lint.yaml"
    lint_agent_content = """
name: lint
version: "1.0"
model:
  plugin: function_gemma
initial_context:
  system_prompt: ""
  user_template: ""
max_turns: 5
termination_tool: submit_result
tools: []
registries: []
"""
    lint_agent.write_text(lint_agent_content, encoding="utf-8")

    monkeypatch.setattr(cli, "_fetch_models", lambda *_args, **_kwargs: {"demo"})

    runner = CliRunner()
    result = runner.invoke(app, ["list-agents", "--config", str(config_file)])

    assert result.exit_code == 0
    assert "lint" in result.output
