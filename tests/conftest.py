"""Shared pytest fixtures for the PDO test suite."""

from __future__ import annotations

from pathlib import Path

import pytest

from pdo.config import PdoConfig


@pytest.fixture()
def tmp_data_dir(tmp_path: Path) -> Path:
    """Create and return an isolated data directory under ``tmp_path``."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return data_dir


@pytest.fixture()
def test_config(tmp_path: Path) -> PdoConfig:
    """Return a ``PdoConfig`` pointing entirely at temporary directories."""
    return PdoConfig(
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        socket_path=tmp_path / "pdo.sock",
        config_file_path=tmp_path / "config.toml",
    )
