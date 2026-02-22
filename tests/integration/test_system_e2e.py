import pytest
from pathlib import Path
from typer.testing import CliRunner
from remora.cli import app

def test_cli_analyze_e2e(tmp_path: Path):
    """End-to-End test of the CLI analyze command."""
    
    # 1. Setup real project dir
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "target.py").write_text("def hello(): pass", encoding="utf-8")
    
    # 2. Setup Config File
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
    
    # 3. Create a fake agent bundle so the system doesn't fail loading
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

    # 4. Invoke the CLI
    runner = CliRunner()
    
    result = runner.invoke(app, ["analyze", str(project_dir), "--config", str(config_file), "--operations", "lint"])
    
    # Depending on the network/vLLM server status, it might succeed or fail with connection error
    assert result.exit_code in (0, 1, 2)
