import json
from pathlib import Path

from click.testing import CliRunner

from pdo.cli.main import cli


def test_status_json_output(tmp_path: Path):
    runner = CliRunner()
    # It should output real JSON even if there's no daemon running
    result = runner.invoke(cli, ["status", "--json"])
    assert result.exit_code == 0
    # ensure we can parse it
    data = json.loads(result.output)
    assert "success" in data or "running" in data or "stage" in data


def test_daemon_status_json_output(tmp_path: Path):
    runner = CliRunner()
    result = runner.invoke(cli, ["daemon", "status", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "running" in data


def test_optimizer_list_json_output(tmp_path: Path):
    runner = CliRunner()
    result = runner.invoke(cli, ["optimizer", "list", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "optimizers" in data
    assert "default" in data


def test_config_list_json_output(tmp_path: Path):
    runner = CliRunner()
    result = runner.invoke(cli, ["config", "list", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "success" in data or "config" in data


def test_logs_json_output_error(tmp_path: Path):
    runner = CliRunner()
    result = runner.invoke(cli, ["logs", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["success"] is False
    assert "error" in data
