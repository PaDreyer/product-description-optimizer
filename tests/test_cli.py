"""Tests for the CLI commands (``pdo.cli``)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from pdo.cli.main import cli
from pdo.protocol.messages import Response


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


def _mock_response(success: bool = True, data: dict | None = None, error: str | None = None):
    """Create a mock Response."""
    return Response(success=success, data=data or {}, error=error)


# ── Help & Version ───────────────────────────────────────────────────


class TestRootCli:
    def test_help_shows_all_commands(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        expected = [
            "daemon",
            "import",
            "optimize",
            "optimizer",
            "export",
            "status",
            "pause",
            "resume",
            "reset",
            "logs",
            "version",
        ]
        for cmd in expected:
            assert cmd in result.output

    def test_version(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["version"])
        assert result.exit_code == 0
        assert "Client version:" in result.output


# ── Daemon Commands ──────────────────────────────────────────────────


class TestDaemonCommands:
    @patch("pdo.cli.daemon_cmd.is_daemon_running", return_value=False)
    def test_daemon_status_stopped(self, mock_running, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["daemon", "status"])
        assert result.exit_code == 0
        assert "stopped" in result.output

    @patch("pdo.cli.daemon_cmd.is_daemon_running", return_value=True)
    @patch("pdo.cli.client.send_command")
    def test_daemon_status_running(self, mock_cmd, mock_running, runner: CliRunner) -> None:
        mock_cmd.return_value = _mock_response(success=True, data={"message": "pong"})
        result = runner.invoke(cli, ["daemon", "status"])
        assert result.exit_code == 0
        assert "running" in result.output

    @patch("pdo.cli.client.send_command")
    def test_daemon_stop(self, mock_cmd, runner: CliRunner) -> None:
        mock_cmd.return_value = _mock_response(success=True)
        result = runner.invoke(cli, ["daemon", "stop"])
        assert result.exit_code == 0
        assert "stopping" in result.output.lower()

    @patch("pdo.daemon.pid.send_signal")
    @patch("pdo.daemon.pid.remove_pid")
    def test_daemon_stop_force(self, mock_remove, mock_kill, runner: CliRunner) -> None:
        mock_kill.return_value = True
        result = runner.invoke(cli, ["daemon", "stop", "--force"])
        assert result.exit_code == 0
        assert "force-killed" in result.output
        mock_kill.assert_called_once()
        mock_remove.assert_called_once()

    @patch("pdo.cli.client.send_command")
    def test_daemon_stop_fallback_hint(self, mock_cmd, runner: CliRunner) -> None:
        mock_cmd.return_value = _mock_response(success=False, error="Version mismatch")
        result = runner.invoke(cli, ["daemon", "stop"])
        assert result.exit_code == 0
        assert "pdo daemon stop" in result.output
        assert "--force" in result.output
        assert "pdo daemon repair" in result.output

    @patch("pdo.daemon.pid.send_signal")
    @patch("pdo.daemon.pid.remove_pid")
    def test_daemon_repair(self, mock_remove, mock_kill, runner: CliRunner) -> None:
        mock_kill.return_value = True
        result = runner.invoke(cli, ["daemon", "repair"])
        assert result.exit_code == 0
        assert "Commencing daemon repair" in result.output
        assert "Cleaned up stale PID" in result.output
        mock_remove.assert_called_once()


# ── Import Command ───────────────────────────────────────────────────


class TestImportCommand:
    def test_import_no_mapping(self, runner: CliRunner, tmp_path: Path) -> None:
        csv_file = tmp_path / "test.csv"
        csv_file.write_text('"A";"B"\n"1";"2"\n')
        result = runner.invoke(cli, ["import", str(csv_file)])
        assert result.exit_code != 0
        assert "mapping" in result.output.lower()

    def test_import_invalid_mapping(self, runner: CliRunner, tmp_path: Path) -> None:
        csv_file = tmp_path / "test.csv"
        csv_file.write_text('"A";"B"\n"1";"2"\n')
        result = runner.invoke(cli, ["import", str(csv_file), "-m", "bad_format"])
        assert result.exit_code != 0
        assert "ROLE:COLUMN" in result.output

    def test_import_unknown_role(self, runner: CliRunner, tmp_path: Path) -> None:
        csv_file = tmp_path / "test.csv"
        csv_file.write_text('"A";"B"\n"1";"2"\n')
        result = runner.invoke(cli, ["import", str(csv_file), "-m", "wrong:A"])
        assert result.exit_code != 0
        assert "Unknown role" in result.output

    @patch("pdo.cli.client.send_command")
    def test_import_success(self, mock_cmd, runner: CliRunner, tmp_path: Path) -> None:
        csv_file = tmp_path / "test.csv"
        csv_file.write_text('"A";"B"\n"1";"2"\n')
        mock_cmd.return_value = _mock_response(success=True, data={"message": "Import started"})
        result = runner.invoke(
            cli, ["import", str(csv_file), "-m", "description:A", "-m", "product_id:B"]
        )
        assert result.exit_code == 0
        assert "Import started" in result.output

    def test_import_missing_file(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["import", "/nonexistent.csv", "-m", "description:A"])
        assert result.exit_code != 0


# ── Optimize Command ─────────────────────────────────────────────────


class TestOptimizeCommand:
    @patch("pdo.cli.client.send_command")
    def test_optimize_success(self, mock_cmd, runner: CliRunner) -> None:
        mock_cmd.return_value = _mock_response(
            success=True, data={"message": "Optimization started"}
        )
        result = runner.invoke(cli, ["optimize"])
        assert result.exit_code == 0
        assert "started" in result.output.lower()
        mock_cmd.assert_called_once_with("optimize", payload=None)

    @patch("pdo.cli.client.send_command")
    def test_optimize_with_flags(self, mock_cmd, runner: CliRunner) -> None:
        mock_cmd.return_value = _mock_response(
            success=True, data={"message": "Optimization started"}
        )
        result = runner.invoke(cli, ["optimize", "--optimizer", "dummy", "--api-key", "secret"])
        assert result.exit_code == 0
        mock_cmd.assert_called_once_with(
            "optimize", payload={"optimizer": "dummy", "api_key": "secret"}
        )

    def test_optimize_unknown_backend(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["optimize", "--optimizer", "doesnotexist"])
        assert result.exit_code != 0
        assert "Unknown optimizer" in result.output

    @patch("pdo.cli.client.send_command")
    def test_optimize_worker_busy(self, mock_cmd, runner: CliRunner) -> None:
        mock_cmd.return_value = _mock_response(success=False, error="Worker is busy")
        result = runner.invoke(cli, ["optimize"])
        assert result.exit_code == 0
        assert "busy" in result.output.lower()


# ── Optimizer Command ────────────────────────────────────────────────


class TestOptimizerCommand:
    def test_optimizer_list(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["optimizer", "list"])
        assert result.exit_code == 0
        assert "dummy" in result.output
        assert "gemini" in result.output
        assert "Active:" in result.output


# ── Export Command ───────────────────────────────────────────────────


class TestExportCommand:
    @patch("pdo.cli.client.send_command")
    def test_export_success(self, mock_cmd, runner: CliRunner, tmp_path: Path) -> None:
        out = tmp_path / "out.csv"
        mock_cmd.return_value = _mock_response(success=True, data={"message": "Export started"})
        result = runner.invoke(cli, ["export", str(out)])
        assert result.exit_code == 0
        assert "Export started" in result.output


# ── Status / Pause / Resume / Reset ─────────────────────────────────


class TestControlCommands:
    @patch("pdo.cli.client.send_command")
    def test_status_displays_progress(self, mock_cmd, runner: CliRunner) -> None:
        mock_cmd.return_value = _mock_response(
            success=True,
            data={
                "stage": "optimizing",
                "progress": {"total": 100, "done": 42, "error": 3, "pending": 55},
                "paused": False,
            },
        )
        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 0
        assert "optimizing" in result.output
        assert "42" in result.output
        assert "100" in result.output

    @patch("pdo.cli.client.send_command")
    def test_pause(self, mock_cmd, runner: CliRunner) -> None:
        mock_cmd.return_value = _mock_response(success=True)
        result = runner.invoke(cli, ["pause"])
        assert result.exit_code == 0
        assert "Paused" in result.output

    @patch("pdo.cli.client.send_command")
    def test_resume(self, mock_cmd, runner: CliRunner) -> None:
        mock_cmd.return_value = _mock_response(success=True)
        result = runner.invoke(cli, ["resume"])
        assert result.exit_code == 0
        assert "Resumed" in result.output

    @patch("pdo.cli.client.send_command")
    def test_reset_with_yes(self, mock_cmd, runner: CliRunner) -> None:
        mock_cmd.return_value = _mock_response(success=True)
        result = runner.invoke(cli, ["reset", "--yes"])
        assert result.exit_code == 0
        assert "reset" in result.output.lower()

    def test_reset_aborted(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["reset"], input="n\n")
        assert result.exit_code == 0
        assert "Aborted" in result.output


# ── Logs Command ─────────────────────────────────────────────────────


class TestLogsCommand:
    def test_logs_no_file(self, runner: CliRunner) -> None:
        with patch("pdo.cli.logs_cmd.load_config") as mock_config:
            mock_config.return_value.log_dir = Path("/tmp/nonexistent_pdo_test")
            result = runner.invoke(cli, ["logs"])
            assert result.exit_code == 0
            assert "No log file" in result.output

    def test_logs_prints_tail(self, runner: CliRunner, tmp_path: Path) -> None:
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        log_file = log_dir / "daemon.log"
        log_file.write_text("\n".join(f"line {i}" for i in range(100)))

        with patch("pdo.cli.logs_cmd.load_config") as mock_config:
            mock_config.return_value.log_dir = log_dir
            result = runner.invoke(cli, ["logs", "-n", "5"])
            assert result.exit_code == 0
            assert "line 99" in result.output
            assert "line 95" in result.output
            # Should NOT contain earlier lines
            assert "line 0" not in result.output
