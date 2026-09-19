"""Safe process shutdown and runtime-file cleanup for the shared daemon."""

from __future__ import annotations

import os
import signal
from collections.abc import Iterator
from contextlib import contextmanager

from pdo.cli.client import send_command
from pdo.config import PdoConfig
from pdo.core.instance_lock import InstanceLock
from pdo.daemon.endpoint import remove_endpoint
from pdo.daemon.pid import read_pid, remove_pid, send_signal, wait_for_exit
from pdo.exceptions import DaemonNotRunningError


@contextmanager
def lifecycle_lock(config: PdoConfig) -> Iterator[None]:
    """Serialize client-side daemon start and stop operations.

    Args:
        config: Configuration containing the shared data directory.

    Yields:
        While this client owns the lifecycle lock.
    """
    lock = InstanceLock(config.data_dir / "launch.lock")
    lock.acquire(blocking=True)
    try:
        yield
    finally:
        lock.release()


def stop_daemon(config: PdoConfig, *, timeout: float = 15.0) -> bool:
    """Stop the shared daemon through IPC or its validated PID, then wait.

    Args:
        config: Configuration shared by the daemon and client.
        timeout: Maximum process shutdown wait in seconds.

    Returns:
        Whether a daemon was present.

    Raises:
        RuntimeError: If the daemon rejects shutdown or does not exit.
    """
    with lifecycle_lock(config):
        pid = read_pid(config.data_dir / "daemon.pid")
        try:
            response = send_command("stop", config=config)
        except DaemonNotRunningError:
            if pid == os.getpid():
                raise RuntimeError(
                    "Cannot stop a daemon running inside this client process."
                ) from None
            if pid is not None:
                stop_process(config, timeout=timeout)
            clean_stale_runtime(config)
            return pid is not None
        if not response.success:
            raise RuntimeError(response.error or "Could not stop the PDO daemon.")
        if pid is not None and pid != os.getpid() and not wait_for_exit(pid, timeout):
            raise RuntimeError("The PDO daemon did not stop in time.")
        return True


def stop_process(config: PdoConfig, *, timeout: float, force: bool = False) -> bool:
    """Stop a validated daemon process and wait for it to release its resources.

    Args:
        config: Configuration containing the daemon PID file.
        timeout: Maximum wait after each shutdown signal.
        force: Send SIGKILL after a graceful shutdown timeout, when available.

    Returns:
        Whether a live, validated daemon process was found.

    Raises:
        RuntimeError: If the process cannot be stopped safely.
    """
    pid_path = config.data_dir / "daemon.pid"
    pid = read_pid(pid_path)
    if pid is None:
        return False
    if not send_signal(pid_path, signal.SIGTERM):
        if wait_for_exit(pid, 0):
            return True
        raise RuntimeError("Could not signal the daemon; its process identity may have changed.")
    if wait_for_exit(pid, timeout):
        return True
    kill_signal = getattr(signal, "SIGKILL", None)
    if (
        force
        and kill_signal is not None
        and send_signal(pid_path, kill_signal)
        and wait_for_exit(pid, timeout)
    ):
        return True
    raise RuntimeError("The daemon did not stop in time; its runtime files were preserved.")


def clean_stale_runtime(config: PdoConfig) -> None:
    """Remove runtime files only while holding the data-directory lock.

    Args:
        config: Configuration containing the runtime paths.

    Raises:
        InstanceAlreadyRunningError: If a process still owns the directory.
    """
    with InstanceLock(config.data_dir / "pdo.lock"):
        remove_pid(config.data_dir / "daemon.pid")
        remove_endpoint(config)
