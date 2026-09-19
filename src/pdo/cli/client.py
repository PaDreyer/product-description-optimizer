"""Thin IPC client used by CLI and desktop clients."""

from __future__ import annotations

import socket
from typing import Any

from pdo.config import PdoConfig, load_config
from pdo.daemon.endpoint import read_endpoint
from pdo.exceptions import DaemonNotRunningError, ProtocolError
from pdo.protocol.messages import (
    Request,
    Response,
    receive_message,
    send_message,
)

_TIMEOUT = 10.0  # seconds


def connect(config: PdoConfig | None = None) -> tuple[socket.socket, str]:
    """Open a connection to the daemon's loopback endpoint.

    Args:
        config: Optional config override.

    Returns:
        Connected TCP socket and the endpoint authentication token.

    Raises:
        DaemonNotRunningError: If the daemon is not running or unreachable.
    """
    cfg = config or load_config()
    endpoint = read_endpoint(cfg)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(_TIMEOUT)
    try:
        sock.connect(("127.0.0.1", endpoint.port))
    except OSError as exc:
        sock.close()
        raise DaemonNotRunningError(
            "Cannot connect to daemon. Is it running? Try: pdo daemon start"
        ) from exc
    return sock, endpoint.token


def send_command(
    action: str,
    payload: dict[str, Any] | None = None,
    *,
    config: PdoConfig | None = None,
) -> Response:
    """Send a command to the daemon and return the response.

    Args:
        action: The IPC action name (e.g. ``"import"``, ``"status"``).
        payload: Optional payload dict.
        config: Optional config override.

    Returns:
        The daemon's :class:`Response`.

    Raises:
        DaemonNotRunningError: If the daemon is unreachable.
    """
    sock, token = connect(config)
    try:
        request = Request(action=action, payload=payload or {}, auth_token=token)
        send_message(sock, request)
        raw = receive_message(sock)
        return Response(**raw)
    except Exception as exc:
        if isinstance(exc, (DaemonNotRunningError, ProtocolError)):
            raise
        raise DaemonNotRunningError(f"Communication error: {exc}") from exc
    finally:
        sock.close()
