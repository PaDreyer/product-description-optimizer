"""One-shot startup notification from a detached daemon to its launcher."""

from __future__ import annotations

import json
import socket
import time

from pdo.protocol.messages import receive_message


def notify_launcher(port: int | None, token: str | None, *, error: str | None = None) -> None:
    """Report daemon readiness or a startup error to the waiting launcher.

    Args:
        port: The launcher's temporary loopback listening port.
        token: Per-launch secret used to match the child to its launcher.
        error: Startup error, or ``None`` when the daemon is ready.
    """
    if port is None or token is None:
        return
    payload = {"token": token, "ready": error is None, "error": error}
    with socket.create_connection(("127.0.0.1", port), timeout=2.0) as connection:
        connection.sendall((json.dumps(payload) + "\n").encode("utf-8"))


def wait_for_startup(listener: socket.socket, *, token: str, timeout: float) -> None:
    """Wait for the child to report its startup result without polling.

    Args:
        listener: Loopback listener owned by the launcher.
        token: Secret passed only to this child process.
        timeout: Maximum wait in seconds.

    Raises:
        RuntimeError: If the child reported a startup failure or invalid message.
        TimeoutError: If no notification arrived in time.
    """
    deadline = time.monotonic() + timeout
    listener.settimeout(timeout)
    try:
        connection, _ = listener.accept()
    except TimeoutError as exc:
        raise TimeoutError("The PDO daemon did not report startup in time.") from exc
    with connection:
        message = receive_message(connection, deadline=deadline)
    if message.get("token") != token:
        raise RuntimeError("Received an invalid PDO daemon startup notification.")
    if not message.get("ready"):
        raise RuntimeError(str(message.get("error") or "The PDO daemon could not start."))
