"""Application configuration with layered priority resolution.

Priority (highest → lowest):
    1. CLI flags / arguments
    2. Environment variables (``PDO_`` prefix)
    3. Config file (``~/.pdo/config.toml``)
    4. Built-in defaults
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

_DEFAULT_BASE_DIR = Path.home() / ".pdo"


@dataclass(frozen=True)
class PdoConfig:
    """Immutable runtime configuration for the PDO application."""

    data_dir: Path = field(default_factory=lambda: _DEFAULT_BASE_DIR / "data")
    log_dir: Path = field(default_factory=lambda: _DEFAULT_BASE_DIR / "logs")
    socket_path: Path = field(default_factory=lambda: _DEFAULT_BASE_DIR / "pdo.sock")
    config_file_path: Path = field(default_factory=lambda: _DEFAULT_BASE_DIR / "config.toml")
    optimizer: str = "auto"
    options: dict[str, str] = field(default_factory=dict)


def _read_config_file(path: Path) -> dict[str, str]:
    """Read and return the TOML config file as a flat dict.

    Returns an empty dict if the file does not exist or is malformed.
    """
    if not path.is_file():
        return {}
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
        return {k: str(v) for k, v in data.get("pdo", {}).items()}
    except (tomllib.TOMLDecodeError, OSError):
        return {}


def _env_overrides() -> dict[str, str]:
    """Collect environment variables with the ``PDO_`` prefix.

    Returns a dict with lowercase keys stripped of the prefix.
    Example: ``PDO_DATA_DIR`` → ``data_dir``.
    """
    prefix = "PDO_"
    return {
        k.removeprefix(prefix).lower(): v for k, v in os.environ.items() if k.startswith(prefix)
    }


def load_config(
    *,
    config_file: Path | None = None,
    overrides: dict[str, str] | None = None,
) -> PdoConfig:
    """Build a ``PdoConfig`` by merging all configuration sources.

    Args:
        config_file: Explicit path to a TOML config file.  Falls back to the
            default ``~/.pdo/config.toml`` when *None*.
        overrides: Optional dict of CLI-level overrides (highest priority).

    Returns:
        A fully resolved ``PdoConfig`` instance.
    """
    defaults = PdoConfig()
    cfg_path = config_file or defaults.config_file_path

    # Layer 4 → 3: defaults ← config file
    merged: dict[str, str] = {}
    merged.update(_read_config_file(cfg_path))

    # Layer 2: env vars
    merged.update(_env_overrides())

    # Layer 1: explicit CLI overrides
    if overrides:
        merged.update(overrides)

    return PdoConfig(
        data_dir=Path(merged.pop("data_dir", defaults.data_dir)),
        log_dir=Path(merged.pop("log_dir", defaults.log_dir)),
        socket_path=Path(merged.pop("socket_path", defaults.socket_path)),
        config_file_path=cfg_path,
        optimizer=merged.pop("optimizer", defaults.optimizer),
        options=merged,
    )
