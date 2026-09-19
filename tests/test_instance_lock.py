"""Tests for exclusive access to the shared application data."""

from __future__ import annotations

from pathlib import Path
from threading import Event, Thread

import pytest

from pdo.core.instance_lock import InstanceLock
from pdo.exceptions import InstanceAlreadyRunningError


def test_instance_lock_rejects_second_owner(tmp_path: Path) -> None:
    """Only one process handle may own a data-directory lock."""
    first = InstanceLock(tmp_path / "pdo.lock")
    second = InstanceLock(tmp_path / "pdo.lock")
    first.acquire()
    try:
        with pytest.raises(InstanceAlreadyRunningError):
            second.acquire()
    finally:
        first.release()

    second.acquire()
    second.release()


def test_blocking_lock_waits_for_previous_owner(tmp_path: Path) -> None:
    """Launch coordination waits for the first client's startup to finish."""
    first = InstanceLock(tmp_path / "launch.lock")
    second = InstanceLock(tmp_path / "launch.lock")
    acquired = Event()
    first.acquire()

    def wait_for_lock() -> None:
        second.acquire(blocking=True)
        acquired.set()
        second.release()

    thread = Thread(target=wait_for_lock)
    thread.start()
    try:
        assert not acquired.wait(timeout=0.1)
    finally:
        first.release()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert acquired.is_set()
