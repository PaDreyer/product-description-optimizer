"""Application configuration with layered priority resolution.

Priority (highest → lowest):
    1. CLI flags / arguments
    2. Environment variables (``PDO_`` prefix)
    3. Config file (``~/.pdo/config.toml``)
    4. Built-in defaults
"""

from __future__ import annotations

import json
import os
import tempfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pdo.exceptions import ConfigError

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


def _read_config_file(path: Path, *, strict: bool = False) -> dict[str, str]:
    """Read and return the TOML config file as a flat dict.

    Flattens nested structures (from unquoted dot keys) to dot-separated strings.

    Args:
        path: Configuration file to read.
        strict: Raise :class:`ConfigError` for invalid or unreadable files.

    Returns:
        Flattened values from the ``[pdo]`` section. Missing files return an
        empty dictionary.

    Raises:
        ConfigError: If strict mode is enabled and the file cannot be read.
    """
    if not path.exists():
        return {}
    if not path.is_file():
        if strict:
            raise ConfigError(f"Config path {path} exists but is not a file.")
        return {}
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
        pdo_section = data.get("pdo", {})
        if not isinstance(pdo_section, dict):
            raise ConfigError(
                f"Invalid config format in {path}: [pdo] section must be a dictionary."
            )

        # Flatten nested structures to dot-separated keys
        def flatten_dict(d: dict[str, Any], parent_key: str = "") -> dict[str, str]:
            """Recursively flatten nested dicts to dot-separated keys."""
            result: dict[str, str] = {}
            for key, value in d.items():
                full_key = f"{parent_key}.{key}" if parent_key else key
                if isinstance(value, dict):
                    result.update(flatten_dict(value, full_key))
                else:
                    result[full_key] = str(value)
            return result

        return flatten_dict(pdo_section)
    except ConfigError:
        if strict:
            raise
        return {}
    except (tomllib.TOMLDecodeError, OSError) as exc:
        if strict:
            raise ConfigError(f"Failed to read config file at {path}: {exc}") from exc
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


def save_config_values(path: Path, values: dict[str, str]) -> None:
    """Merge and atomically save application settings.

    Args:
        path: TOML configuration path.
        values: Flat setting names and string values to update.

    Raises:
        ConfigError: If the existing configuration is invalid or the updated
            file cannot be written.
    """
    merged = _read_config_file(path, strict=True)
    merged.update(values)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["[pdo]"]
    for key, value in sorted(merged.items()):
        toml_key = json.dumps(key, ensure_ascii=False)
        toml_value = json.dumps(value, ensure_ascii=False)
        lines.append(f"{toml_key} = {toml_value}")
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=".config-", delete=False
        ) as stream:
            temp_path = Path(stream.name)
            stream.write("\n".join(lines) + "\n")
        if os.name != "nt":
            temp_path.chmod(0o600)
        temp_path.replace(path)
    except OSError as exc:
        raise ConfigError(f"Failed to write config file at {path}: {exc}") from exc
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
