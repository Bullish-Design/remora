from typer.testing import CliRunner

from remora.cli import app


def test_config_command_outputs_yaml() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["config", "--format", "yaml"])
    assert result.exit_code == 0
    assert "agents_dir" in result.output
