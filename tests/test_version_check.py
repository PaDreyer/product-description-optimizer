"""Tests for the IPC version check mechanism."""

import json
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from pdo import __version__
from pdo.cli.client import send_command
from pdo.cli.main import cli
from pdo.daemon.server import DaemonServer
from pdo.exceptions import DaemonNotRunningError
from pdo.protocol.messages import Request, Response


def test_request_carries_client_version():
    """Ensure the client automatically embeds its version into the Request."""
    req = Request(action="ping", payload={"foo": "bar"})
    assert req.client_version == __version__

    data = json.loads(req.to_json())
    assert data["client_version"] == __version__


def test_response_carries_server_version():
    """Ensure the server automatically embeds its version into the Response."""
    resp = Response(success=True, data={"foo": "bar"})
    assert resp.server_version == __version__

    data = json.loads(resp.to_json())
    assert data["server_version"] == __version__


def test_daemon_rejects_version_mismatch():
    """Keep control actions stable but reject versioned data operations."""
    server = DaemonServer()
    server._worker = MagicMock()

    # Valid
    valid_req = Request(action="ping")
    valid_resp = server._dispatch(valid_req)
    assert valid_resp.success is True

    # Invalid
    old_ping = server._dispatch(Request(action="ping", client_version="0.0.1-old"))
    assert old_ping.success is True

    invalid_resp = server._dispatch(Request(action="status", client_version="0.0.1-old"))
    assert invalid_resp.success is False
    assert "Version mismatch" in invalid_resp.error
    assert "0.0.1-old" in invalid_resp.error


@patch("pdo.cli.client.connect")
@patch("pdo.cli.client.send_message")
@patch("pdo.cli.client.receive_message")
def test_send_command_version_mismatch_from_server(mock_recv, mock_send, mock_connect):
    """Ensure send_command correctly surfaces the server's rejection payload."""
    mock_connect.return_value = (MagicMock(), "test-auth-token")
    mock_recv.return_value = {
        "success": False,
        "error": f"Version mismatch: CLI client is v{__version__}, but daemon is v0.0.1-old.",
        "server_version": "0.0.1-old",
    }

    # No exception should be raised locally until the application handles Response.success == False
    response = send_command("ping")
    assert response.success is False
    assert "Version mismatch" in response.error


@patch("pdo.cli.client.send_command")
def test_version_command_daemon_not_running(mock_send):
    """Test `pdo version` when the daemon is offline."""
    mock_send.side_effect = DaemonNotRunningError("offline")

    runner = CliRunner()
    result = runner.invoke(cli, ["version"])

    assert result.exit_code == 0
    assert "Client version:" in result.output
    assert str(__version__) in result.output
    assert "Daemon version: not running" in result.output


@patch("pdo.cli.client.send_command")
def test_version_command_daemon_running(mock_send):
    """Test `pdo version` when the daemon is online."""
    mock_send.return_value = Response(success=True, server_version="0.9.9")

    runner = CliRunner()
    result = runner.invoke(cli, ["version"])

    assert result.exit_code == 0
    assert "Client version:" in result.output
    assert str(__version__) in result.output
    assert "Daemon version: 0.9.9" in result.output


@patch("pdo.cli.client.send_command")
def test_version_command_mismatch(mock_send):
    """Test `pdo version` when there is a mismatch."""
    mock_send.return_value = Response(
        success=False, error="Version mismatch: CLI client is v0.1.0, but daemon is v0.2.0"
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["version"])

    assert result.exit_code == 0
    assert "version mismatch" in result.output
