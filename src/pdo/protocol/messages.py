"""IPC protocol — request/response dataclasses and socket helpers.

Messages are serialised as newline-delimited JSON over Unix domain sockets.
"""

from __future__ import annotations

import json
import socket
from dataclasses import asdict, dataclass, field
from typing import Any, Self

from pdo import __version__
from pdo.exceptions import ProtocolError

# Maximum message size (1 MiB) — prevents unbounded reads.
_MAX_MSG_SIZE = 1 * 1024 * 1024


@dataclass
class Request:
    """CLI → Daemon request."""

    action: str
    payload: dict[str, Any] = field(default_factory=dict)
    client_version: str = field(default=__version__)

    def to_json(self) -> str:
        """Serialise to a JSON string."""
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> Self:
        """Deserialise from a JSON string."""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ProtocolError(f"Invalid JSON in request: {exc}") from exc
        if "action" not in data:
            raise ProtocolError("Request missing 'action' field")
        return cls(
            action=data["action"], 
            payload=data.get("payload", {}),
            client_version=data.get("client_version", "unknown")
        )


@dataclass
class Response:
    """Daemon → CLI response."""

    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    server_version: str = field(default=__version__)

    def to_json(self) -> str:
        """Serialise to a JSON string."""
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> Self:
        """Deserialise from a JSON string."""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ProtocolError(f"Invalid JSON in response: {exc}") from exc
        if "success" not in data:
            raise ProtocolError("Response missing 'success' field")
        return cls(
            success=data["success"],
            data=data.get("data", {}),
            error=data.get("error"),
            server_version=data.get("server_version", "unknown"),
        )


# ── Socket helpers ───────────────────────────────────────────────────


def send_message(sock: socket.socket, msg: Request | Response) -> None:
    """Send a newline-delimited JSON message over the socket."""
    raw = msg.to_json() + "\n"
    sock.sendall(raw.encode("utf-8"))


def receive_message(sock: socket.socket) -> dict[str, Any]:
    """Read a newline-delimited JSON message from the socket.

    Returns the parsed dict.  Raises :class:`ProtocolError` on failure.
    """
    buf = b""
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            if not buf:
                raise ProtocolError("Connection closed before a message was received")
            break
        buf += chunk
        if len(buf) > _MAX_MSG_SIZE:
            raise ProtocolError("Message exceeds maximum size")
        if b"\n" in buf:
            break

    line = buf.split(b"\n", 1)[0]
    try:
        return json.loads(line.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ProtocolError(f"Invalid message: {exc}") from exc
