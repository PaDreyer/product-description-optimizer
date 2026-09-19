"""Start and discover the shared PDO daemon on supported platforms."""

from __future__ import annotations

import json
import os
import secrets
import socket
import subprocess
import sys
from contextlib import suppress

from pdo import __version__
from pdo.cli.client import send_command
from pdo.config import PdoConfig
from pdo.daemon.endpoint import endpoint_file
from pdo.daemon.lifecycle import clean_stale_runtime, lifecycle_lock, stop_process
from pdo.daemon.pid import read_pid, wait_for_exit
from pdo.daemon.startup import wait_for_startup
from pdo.exceptions import DaemonNotRunningError, InstanceAlreadyRunningError
from pdo.protocol.messages import Response, receive_message


def ensure_daemon_running(config: PdoConfig, *, timeout: float = 15.0) -> None:
    """Start a detached daemon if no current-version daemon is available.

    Args:
        config: Configuration and data directory shared by clients.
        timeout: Maximum startup wait in seconds.

    Raises:
        RuntimeError: If the daemon cannot be started before the timeout.
    """
    try:
        with lifecycle_lock(config):
            _ensure_daemon_running_locked(config, timeout=timeout)
    except InstanceAlreadyRunningError as exc:
        raise RuntimeError("Another PDO startup is still in progress.") from exc


def _ensure_daemon_running_locked(config: PdoConfig, *, timeout: float) -> None:
    """Inspect, recover, and start the daemon while holding the launch lock."""
    try:
        response = send_command("ping", config=config)
        if response.success and response.server_version == __version__:
            return
        if response.success:
            _stop_outdated_daemon(config, timeout=timeout)
        else:
            raise RuntimeError(response.error or "The PDO daemon did not respond to ping.")
    except DaemonNotRunningError:
        if os.name != "nt" and config.socket_path.is_socket():
            _stop_legacy_daemon(config, timeout=timeout)
        elif endpoint_file(config).exists() and read_pid(config.data_dir / "daemon.pid"):
            raise RuntimeError(
                "The PDO daemon is running but its endpoint is unresponsive. "
                "Use 'pdo daemon repair' to stop it."
            ) from None
        elif read_pid(config.data_dir / "daemon.pid") is not None:
            # A previous CLI cleanup may have removed the endpoint while the
            # process still owns the database. Restart it without losing data.
            stop_process(config, timeout=timeout)

    try:
        clean_stale_runtime(config)
    except InstanceAlreadyRunningError as exc:
        raise RuntimeError(
            "The PDO data directory is owned by another process. "
            "Close the previous PDO process or use 'pdo daemon repair'."
        ) from exc
    config.data_dir.mkdir(parents=True, exist_ok=True)
    config.log_dir.mkdir(parents=True, exist_ok=True)
    _start_detached_daemon(config, timeout=timeout)


def _start_detached_daemon(config: PdoConfig, *, timeout: float) -> None:
    """Launch one subprocess, wait for readiness, and verify its endpoint."""
    token = secrets.token_urlsafe(32)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        command = _daemon_command(
            config, ready_port=int(listener.getsockname()[1]), ready_token=token
        )
        popen_options: dict[str, object] = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "close_fds": True,
        }
        if os.name == "nt":
            popen_options["creationflags"] = getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0
            ) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        else:
            popen_options["start_new_session"] = True
        startup_log = config.log_dir / "daemon-startup.log"
        with startup_log.open("a", encoding="utf-8") as errors:
            process = subprocess.Popen(command, stderr=errors, **popen_options)
        try:
            wait_for_startup(listener, token=token, timeout=timeout)
        except Exception as exc:
            if process.poll() is None:
                with suppress(ProcessLookupError):
                    process.terminate()
                try:
                    process.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    with suppress(ProcessLookupError):
                        process.kill()
                    process.wait(timeout=5.0)
            if isinstance(exc, TimeoutError):
                raise RuntimeError(f"{exc} See {startup_log} for details.") from exc
            raise

    try:
        response = send_command("ping", config=config)
    except DaemonNotRunningError as exc:
        raise RuntimeError("The PDO daemon reported readiness but cannot be reached.") from exc
    if not response.success or response.server_version != __version__:
        raise RuntimeError(response.error or "The PDO daemon started with an unexpected version.")


def _stop_outdated_daemon(config: PdoConfig, *, timeout: float) -> None:
    """Stop an authenticated daemon from another application version."""
    pid = read_pid(config.data_dir / "daemon.pid")
    if pid is None:
        raise RuntimeError("The existing PDO daemon has no valid process ID.")
    response = send_command("stop", config=config)
    if not response.success:
        raise RuntimeError(response.error or "Could not stop the outdated PDO daemon.")
    if not wait_for_exit(pid, timeout):
        raise RuntimeError("The outdated PDO daemon did not stop in time.")


def _stop_legacy_daemon(config: PdoConfig, *, timeout: float) -> None:
    """Replace a pre-TCP PDO daemon still listening on the Unix socket."""
    if os.name == "nt" or not config.socket_path.is_socket():
        return
    try:
        response = _legacy_command(config, "ping", __version__, timeout=timeout)
    except (ConnectionRefusedError, FileNotFoundError):
        return  # stale socket from a daemon that already exited
    version = __version__
    if not response.success and response.error and response.error.startswith("Version mismatch:"):
        version = response.server_version
        response = _legacy_command(config, "ping", version, timeout=timeout)
    if not response.success or response.data.get("message") != "pong":
        raise RuntimeError("The existing Unix-socket service is not a compatible PDO daemon.")

    response = _legacy_command(config, "stop", version, timeout=timeout)
    if not response.success:
        raise RuntimeError(response.error or "Could not stop the old PDO daemon.")
    pid = read_pid(config.data_dir / "daemon.pid")
    if pid is None or not wait_for_exit(pid, timeout):
        raise RuntimeError("The old PDO daemon did not stop in time.")


def _legacy_command(config: PdoConfig, action: str, version: str, *, timeout: float) -> Response:
    """Send an old protocol request without its unsupported auth-token field."""
    request = {"action": action, "payload": {}, "client_version": version}
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(min(timeout, 5.0))
        connection.connect(str(config.socket_path))
        connection.sendall((json.dumps(request) + "\n").encode("utf-8"))
        return Response(**receive_message(connection))


def _daemon_command(
    config: PdoConfig, *, ready_port: int | None = None, ready_token: str | None = None
) -> list[str]:
    """Build the daemon command for source and packaged installs."""
    appimage = os.environ.get("APPIMAGE")
    if appimage:
        command = [appimage]
    elif getattr(sys, "frozen", False):
        command = [sys.executable]
    else:
        command = [sys.executable, "-m", "pdo.daemon.entry"]
    result = [
        *command,
        "--daemon-process",
        "--daemon-config",
        str(config.config_file_path),
        "--daemon-data-dir",
        str(config.data_dir),
        "--daemon-log-dir",
        str(config.log_dir),
    ]
    if ready_port is not None and ready_token is not None:
        result.extend(["--ready-port", str(ready_port), f"--ready-token={ready_token}"])
    return result
