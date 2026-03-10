"""CLI commands for managing the configuration file."""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import click
from rich.console import Console

from pdo.config import PdoConfig
from pdo.exceptions import ConfigError

console = Console()


def _load_config_dict(path: Path) -> dict[str, str]:
    """Safely load the [pdo] section from the TOML config file."""
    if not path.exists():
        return {}
    
    if not path.is_file():
        raise ConfigError(f"Config path {path} exists but is not a file.")
        
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"Failed to parse config file at {path}: {e}")
    except OSError as e:
        raise ConfigError(f"Failed to read config file at {path}: {e}")

    pdo_section = data.get("pdo", {})
    if not isinstance(pdo_section, dict):
        raise ConfigError(f"Invalid config format in {path}: [pdo] section must be a dictionary.")

    return {k: str(v) for k, v in pdo_section.items()}


def _save_config_dict(path: Path, items: dict[str, str]) -> None:
    """Save the dictionary to the config file under the [pdo] section."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = ["[pdo]"]
        
        # Sort keys for consistent output
        for k in sorted(items.keys()):
            v = items[k]
            # Basic escaping for string values
            escaped_v = v.replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'{k} = "{escaped_v}"')
            
        with path.open("w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    except OSError as e:
        raise ConfigError(f"Failed to write config file at {path}: {e}")


@click.group()
def config() -> None:
    """Manage the PDO configuration file."""


@config.command("set")
@click.argument("key")
@click.argument("value")
@click.pass_context
def set_cmd(ctx: click.Context, key: str, value: str) -> None:
    """Set a configuration key to a given value.
    
    Example: pdo config set log_dir /tmp/logs
    """
    path = ctx.obj.config_path or PdoConfig().config_file_path
    try:
        data = _load_config_dict(path)
        data[key] = value
        _save_config_dict(path, data)
        console.print(f"[green]✓[/green] Set [bold cyan]{key}[/bold cyan] to [bold]{value}[/bold] in {path}")
    except ConfigError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


@config.command("get")
@click.argument("key")
@click.pass_context
def get_cmd(ctx: click.Context, key: str) -> None:
    """Get the value of a configuration key.
    
    Example: pdo config get log_dir
    """
    path = ctx.obj.config_path or PdoConfig().config_file_path
    try:
        data = _load_config_dict(path)
        if key in data:
            console.print(data[key])
        else:
            console.print(f"[yellow]Key '{key}' not found in {path}.[/yellow]")
            sys.exit(1)
    except ConfigError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


@config.command("list")
@click.pass_context
def list_cmd(ctx: click.Context) -> None:
    """List all configuration keys and values.
    
    Example: pdo config list
    """
    path = ctx.obj.config_path or PdoConfig().config_file_path
    try:
        data = _load_config_dict(path)
        if not data:
            console.print(f"[yellow]No configuration found in {path}.[/yellow]")
            return
            
        for k in sorted(data.keys()):
            console.print(f"{k} = {data[k]}")
    except ConfigError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)
