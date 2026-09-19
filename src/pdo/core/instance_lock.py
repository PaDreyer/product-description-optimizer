"""Cross-platform process lock for the shared PDO data directory."""

from __future__ import annotations

import errno
import os
from pathlib import Path
from typing import BinaryIO

from pdo.exceptions import InstanceAlreadyRunningError


class InstanceLock:
    """Hold an advisory file lock until :meth:`release` is called."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._stream: BinaryIO | None = None

    def acquire(self, *, blocking: bool = False) -> None:
        """Acquire the process lock.

        Args:
            blocking: Wait for the lock instead of failing immediately.

        Raises:
            InstanceAlreadyRunningError: If another process owns the lock.
            OSError: If the lock file cannot be opened.
        """
        if self._stream is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        stream = os.fdopen(fd, "r+b")
        try:
            if os.name == "nt":
                self._acquire_windows(stream, blocking=blocking)
            else:
                self._acquire_posix(stream, blocking=blocking)
        except OSError as exc:
            stream.close()
            if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK}:
                raise InstanceAlreadyRunningError(
                    "The PDO data directory is already owned by another daemon."
                ) from exc
            raise
        stream.seek(0)
        stream.truncate()
        stream.write(f"{os.getpid()}\n".encode())
        stream.flush()
        self._stream = stream

    def release(self) -> None:
        """Release the lock and close its file handle."""
        if self._stream is None:
            return
        stream = self._stream
        self._stream = None
        try:
            if os.name == "nt":
                import msvcrt

                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        finally:
            stream.close()

    @staticmethod
    def _acquire_posix(stream: BinaryIO, *, blocking: bool) -> None:
        """Acquire a POSIX advisory lock."""
        import fcntl

        flags = fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB
        fcntl.flock(stream.fileno(), flags)

    @staticmethod
    def _acquire_windows(stream: BinaryIO, *, blocking: bool) -> None:
        """Acquire a one-byte Windows file lock."""
        import msvcrt

        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        mode = msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK
        msvcrt.locking(stream.fileno(), mode, 1)

    def __enter__(self) -> InstanceLock:
        self.acquire()
        return self

    def __exit__(self, *_: object) -> None:
        self.release()
