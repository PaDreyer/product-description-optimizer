"""CLI commands for managing the configuration file."""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path
from typing import Any

import click

from pdo.cli.common import global_options
from pdo.config import PdoConfig, save_config_values
from pdo.exceptions import ConfigError


def _load_config_dict(path: Path) -> dict[str, str]:
    """Safely load the [pdo] section from the TOML config file.

    Handles both nested TOML structures (from dot-separated keys) and flat keys.
    Flattens nested structures to dot-separated strings.
    """
    if not path.exists():
        return {}

    if not path.is_file():
        raise ConfigError(f"Config path {path} exists but is not a file.")

    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
        pdo_section = data.get("pdo", {})
        if not isinstance(pdo_section, dict):
            raise ConfigError(
                f"Invalid config format in {path}: [pdo] section must be a dictionary."
            )

        # Flatten nested structures (from unquoted dot keys) to dot-separated keys
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
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"Failed to parse config file at {path}: {e}") from e
    except OSError as e:
        raise ConfigError(f"Failed to read config file at {path}: {e}") from e


@click.group()
def config() -> None:
    """Manage the PDO configuration file."""


@config.command("set")
@click.argument("key")
@click.argument("value")
@global_options()
@click.pass_context
def set_cmd(ctx: click.Context, key: str, value: str) -> None:
    """Set a configuration key to a given value.

    Example: pdo config set log_dir /tmp/logs
    """
    path = ctx.obj.config_path or PdoConfig().config_file_path
    try:
        save_config_values(path, {key: value})
        ctx.obj.out.result(
            success=True,
            key=key,
            value=value,
            msg=(
                f"[green]✓[/green] Set [bold cyan]{key}[/bold cyan] "
                f"to [bold]{value}[/bold] in {path}"
            ),
        )
    except ConfigError as e:
        ctx.obj.out.result(success=False, error=str(e))
        sys.exit(1)


@config.command("get")
@click.argument("key")
@global_options()
@click.pass_context
def get_cmd(ctx: click.Context, key: str) -> None:
    """Get the value of a configuration key.

    Example: pdo config get log_dir
    """
    path = ctx.obj.config_path or PdoConfig().config_file_path
    try:
        data = _load_config_dict(path)
        if key in data:
            ctx.obj.out.result(success=True, key=key, value=data[key], msg=data[key])
        else:
            ctx.obj.out.result(
                success=False,
                error=f"Key '{key}' not found",
                msg=f"[yellow]Key '{key}' not found in {path}.[/yellow]",
            )
            sys.exit(1)
    except ConfigError as e:
        ctx.obj.out.result(success=False, error=str(e))
        sys.exit(1)


@config.command("list")
@global_options()
@click.pass_context
def list_cmd(ctx: click.Context) -> None:
    """List all configuration keys and values.

    Example: pdo config list
    """
    path = ctx.obj.config_path or PdoConfig().config_file_path
    try:
        data = _load_config_dict(path)
        if ctx.obj.json_output:
            ctx.obj.out.result(success=True, config=data)
            return

        if not data:
            ctx.obj.out.print(f"[yellow]No configuration found in {path}.[/yellow]")
            return

        for k in sorted(data.keys()):
            ctx.obj.out.print(f"{k} = {data[k]}")
    except ConfigError as e:
        ctx.obj.out.result(success=False, error=str(e))
        sys.exit(1)
