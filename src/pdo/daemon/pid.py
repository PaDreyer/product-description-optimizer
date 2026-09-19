"""PID file management with process identity validation."""

from __future__ import annotations

import json
import os
import select
import signal
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class _PidRecord:
    pid: int
    started: str | None


def write_pid(pid_path: Path) -> None:
    """Atomically write the current PID and process start identity."""
    pid = os.getpid()
    record = {"pid": pid, "started": _process_marker(pid)}
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=pid_path.parent,
            prefix=".daemon-pid-",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(record, stream)
            stream.write("\n")
        if os.name != "nt":
            temporary.chmod(0o600)
        temporary.replace(pid_path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def read_pid(pid_path: Path) -> int | None:
    """Read a PID whose stored process identity still matches."""
    record = _read_record(pid_path)
    if record is None:
        return None
    if record.started is not None and _process_marker(record.pid) != record.started:
        return None
    return record.pid


def is_daemon_running(pid_path: Path) -> bool:
    """Return whether the validated daemon process is still alive."""
    pid = read_pid(pid_path)
    if pid is None:
        return False
    if os.name == "nt":
        return _windows_process_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _windows_process_alive(pid: int) -> bool:
    """Check Windows process liveness without sending a terminating signal."""
    return _wait_windows_process(pid, 0) == 0x00000102  # WAIT_TIMEOUT


def wait_for_exit(pid: int, timeout: float) -> bool:
    """Wait for a known process to exit without polling or sending a signal.

    Args:
        pid: Process ID captured before requesting shutdown.
        timeout: Maximum wait in seconds.

    Returns:
        Whether the process exited within the timeout.
    """
    if os.name == "nt":
        return _wait_windows_process(pid, round(timeout * 1000)) == 0  # WAIT_OBJECT_0
    try:
        descriptor = os.pidfd_open(pid)
    except ProcessLookupError:
        return True
    try:
        readable, _, _ = select.select([descriptor], [], [], timeout)
        return bool(readable)
    finally:
        os.close(descriptor)


def _wait_windows_process(pid: int, timeout_ms: int) -> int | None:
    """Return the Windows wait result, or ``None`` if no handle exists."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
    if not handle:
        error = ctypes.get_last_error()
        if error in {87, 1168}:  # ERROR_INVALID_PARAMETER / ERROR_NOT_FOUND
            return 0  # WAIT_OBJECT_0: the process no longer exists
        raise ctypes.WinError(error)
    try:
        return kernel32.WaitForSingleObject(handle, timeout_ms)
    finally:
        kernel32.CloseHandle(handle)


def remove_pid(pid_path: Path) -> None:
    """Remove the PID file if it exists."""
    pid_path.unlink(missing_ok=True)


def send_signal(pid_path: Path, sig: signal.Signals = signal.SIGTERM) -> bool:
    """Signal only a process whose stored start identity still matches."""
    record = _read_record(pid_path)
    if record is None or record.started is None or _process_marker(record.pid) != record.started:
        return False
    try:
        os.kill(record.pid, sig)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def _read_record(pid_path: Path) -> _PidRecord | None:
    """Read the current JSON format and legacy integer files."""
    if not pid_path.is_file():
        return None
    try:
        text = pid_path.read_text(encoding="utf-8").strip()
        try:
            raw = json.loads(text)
        except json.JSONDecodeError:
            return _PidRecord(pid=int(text), started=None)
        if isinstance(raw, int):
            return _PidRecord(pid=raw, started=None)
        pid = int(raw["pid"])
        started = raw.get("started")
        if started is not None and not isinstance(started, str):
            return None
        return _PidRecord(pid=pid, started=started)
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _process_marker(pid: int) -> str | None:
    """Return an OS process creation marker that survives PID reuse."""
    if os.name == "nt":
        return _windows_process_marker(pid)
    stat_path = Path(f"/proc/{pid}/stat")
    try:
        stat = stat_path.read_text(encoding="ascii")
        fields = stat[stat.rfind(")") + 2 :].split()
        return f"proc:{fields[19]}"
    except (OSError, IndexError):
        return None


def _windows_process_marker(pid: int) -> str | None:
    """Return the Windows process creation FILETIME using only stdlib."""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetProcessTimes.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
    ]
    kernel32.GetProcessTimes.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    creation = wintypes.FILETIME()
    exit_time = wintypes.FILETIME()
    kernel = wintypes.FILETIME()
    user = wintypes.FILETIME()
    try:
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel),
            ctypes.byref(user),
        ):
            return None
        value = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
        return f"win:{value}"
    finally:
        kernel32.CloseHandle(handle)
