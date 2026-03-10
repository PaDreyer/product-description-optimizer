"""Thin IPC client — used by every CLI command to talk to the daemon.

Connects to the daemon's Unix domain socket, sends a JSON request,
and returns the parsed response.
"""

from __future__ import annotations

import socket
from typing import Any

from pdo.config import PdoConfig, load_config
from pdo.exceptions import DaemonNotRunningError
from pdo.protocol.messages import (
    Request,
    Response,
    receive_message,
    send_message,
)

_TIMEOUT = 10.0  # seconds


def connect(config: PdoConfig | None = None) -> socket.socket:
    """Open a connection to the daemon socket.

    Raises:
        DaemonNotRunningError: If the daemon is not running or the socket
            file does not exist.
    """
    cfg = config or load_config()
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(_TIMEOUT)
    try:
        sock.connect(str(cfg.socket_path))
    except (ConnectionRefusedError, FileNotFoundError, OSError) as exc:
        sock.close()
        raise DaemonNotRunningError(
            "Cannot connect to daemon. Is it running? Try: pdo daemon start"
        ) from exc
    return sock


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
    sock = connect(config)
    try:
        request = Request(action=action, payload=payload or {})
        send_message(sock, request)
        raw = receive_message(sock)
        return Response(**raw)
    except Exception as exc:
        if isinstance(exc, DaemonNotRunningError):
            raise
        raise DaemonNotRunningError(f"Communication error: {exc}") from exc
    finally:
        sock.close()
