"""Tests for exclusive access to the shared application data."""

from __future__ import annotations

from pathlib import Path

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
