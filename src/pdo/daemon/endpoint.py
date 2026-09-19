"""Authenticated local TCP endpoint discovery for the PDO daemon."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from pdo.config import PdoConfig
from pdo.exceptions import DaemonNotRunningError


@dataclass(frozen=True)
class DaemonEndpoint:
    """Connection details shared through a user-readable file."""

    port: int
    token: str


def endpoint_file(config: PdoConfig) -> Path:
    """Return the daemon endpoint file for a configuration.

    Args:
        config: Application configuration.

    Returns:
        Path to the user-local daemon endpoint file.
    """
    return config.data_dir / "daemon.endpoint"


def read_endpoint(config: PdoConfig) -> DaemonEndpoint:
    """Read and validate the daemon's loopback endpoint.

    Args:
        config: Application configuration.

    Returns:
        Port and authentication token published by the daemon.

    Raises:
        DaemonNotRunningError: If the endpoint file is missing or invalid.
    """
    path = endpoint_file(config)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        port = int(raw["port"])
        token = str(raw["token"])
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise DaemonNotRunningError("Cannot find the daemon endpoint. Is it running?") from exc
    if not 1 <= port <= 65535 or len(token) < 32:
        raise DaemonNotRunningError("The daemon endpoint file is invalid.")
    return DaemonEndpoint(port=port, token=token)


def write_endpoint(config: PdoConfig, endpoint: DaemonEndpoint) -> None:
    """Atomically publish the daemon's authenticated loopback endpoint.

    Args:
        config: Application configuration.
        endpoint: Bound TCP port and random authentication token.
    """
    path = endpoint_file(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=".daemon-endpoint-",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump({"port": endpoint.port, "token": endpoint.token}, stream)
            stream.write("\n")
        if os.name != "nt":
            temporary.chmod(0o600)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def remove_endpoint(config: PdoConfig) -> None:
    """Remove a stale daemon endpoint file.

    Args:
        config: Application configuration.
    """
    endpoint_file(config).unlink(missing_ok=True)
