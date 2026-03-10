"""Common CLI utilities and context."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import click
from rich.console import Console

console = Console()


class OutputManager:
    """Handles routing output as either human-readable rich text or raw JSON payloads."""

    def __init__(self, json_output: bool = False) -> None:
        self.json_output = json_output

    def print(self, message: str, highlight: bool = True) -> None:
        """Print a message to the console. No-op if JSON output is enabled."""
        if not self.json_output:
            console.print(message, highlight=highlight)

    def error(self, message: str) -> None:
        """Print an error message. No-op if JSON output is enabled."""
        if not self.json_output:
            console.print(f"[red]Error:[/red] {message}")

    def emit_json(self, data: dict[str, Any] | list[Any]) -> None:
        """Safely echo a JSON string. No-op if JSON output is NOT enabled."""
        if self.json_output:
            click.echo(json.dumps(data, ensure_ascii=False))

    def result(
        self,
        success: bool,
        data: dict[str, Any] | None = None,
        error: str | None = None,
        msg: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Standardize the final command result payload and printing.

        If json_output is True, emits a combined payload.
        If json_output is False, prints the `msg` (for success) or `error` (for failure).
        """
        if self.json_output:
            payload: dict[str, Any] = {"success": success}
            if data is not None:
                payload.update(data)
            if error is not None:
                payload["error"] = error
            if kwargs:
                payload.update(kwargs)
            self.emit_json(payload)
        else:
            if not success and error is not None:
                self.error(error)
            elif success and msg is not None:
                self.print(msg)


class _CliContext:
    """Simple namespace stored in ``click.Context.obj`` to share global flags."""

    def __init__(self) -> None:
        self.out = OutputManager(json_output=False)
        self.verbose: bool = False
        self.config_path: Path | None = None

    @property
    def json_output(self) -> bool:
        return self.out.json_output

    @json_output.setter
    def json_output(self, value: bool) -> None:
        self.out.json_output = value


def set_json(ctx: click.Context, param: click.Parameter, value: bool) -> bool:
    """Click callback to set the JSON output flag globally."""
    if value:
        ctx.ensure_object(_CliContext)
        ctx.obj.json_output = True
    return value


def set_verbose(ctx: click.Context, param: click.Parameter, value: bool) -> bool:
    """Click callback to set the verbose flag globally."""
    if value:
        ctx.ensure_object(_CliContext)
        ctx.obj.verbose = True
    return value


def global_options() -> Callable[[click.Command], click.Command]:
    """Decorator to add global options (like --json, --verbose) to any command
    without requiring them in the function signature.
    """

    def decorator(f: click.Command) -> click.Command:
        f = click.option(
            "--json",
            is_flag=True,
            expose_value=False,
            callback=set_json,
            is_eager=True,
            help="Emit machine-readable JSON output.",
        )(f)
        f = click.option(
            "--verbose",
            "-v",
            is_flag=True,
            expose_value=False,
            callback=set_verbose,
            is_eager=True,
            help="Enable verbose / debug output.",
        )(f)
        return f

    return decorator
