"""PID file management for the daemon process.

The PID file (``~/.pdo/daemon.pid`` by default) records the process ID of a
running daemon so the CLI can detect whether the daemon is alive and signal it.
"""

from __future__ import annotations

import os
import signal
from pathlib import Path


def write_pid(pid_path: Path) -> None:
    """Write the current process PID to *pid_path*."""
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(str(os.getpid()))


def read_pid(pid_path: Path) -> int | None:
    """Read the PID from *pid_path*.

    Returns *None* if the file doesn't exist or contains invalid data.
    """
    if not pid_path.is_file():
        return None
    try:
        return int(pid_path.read_text().strip())
    except (ValueError, OSError):
        return None


def is_daemon_running(pid_path: Path) -> bool:
    """Check whether a daemon process is alive.

    Returns *True* only if the PID file exists **and** the process is still
    running (verified via ``os.kill(pid, 0)``).
    """
    pid = read_pid(pid_path)
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        # Process is gone — stale PID file.
        return False
    except PermissionError:
        # Process exists but we can't signal it (unlikely for same user).
        return True
    return True


def remove_pid(pid_path: Path) -> None:
    """Remove the PID file if it exists."""
    pid_path.unlink(missing_ok=True)


def send_signal(pid_path: Path, sig: signal.Signals = signal.SIGTERM) -> bool:
    """Send a signal to the daemon process.

    Returns *True* if the signal was sent successfully, *False* otherwise.
    """
    pid = read_pid(pid_path)
    if pid is None:
        return False
    try:
        os.kill(pid, sig)
    except (ProcessLookupError, PermissionError):
        return False
    return True
