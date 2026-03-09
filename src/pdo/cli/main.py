"""Root CLI group for the ``pdo`` command.

This module defines the top-level Click group and the global options
(``--json``, ``--verbose``) that all subcommands inherit.
"""

from __future__ import annotations

import click
from rich.console import Console

from pdo import __version__

console = Console()


class _JsonFlag:
    """Simple namespace stored in ``click.Context.obj`` to share global flags."""

    def __init__(self) -> None:
        self.json_output: bool = False
        self.verbose: bool = False


@click.group()
@click.option("--json", "json_output", is_flag=True, help="Emit machine-readable JSON output.")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose / debug output.")
@click.pass_context
def cli(ctx: click.Context, *, json_output: bool, verbose: bool) -> None:
    """PDO — Product Description Optimizer.

    A daemon/client CLI for batch-optimizing product descriptions.
    """
    ctx.ensure_object(_JsonFlag)
    ctx.obj.json_output = json_output
    ctx.obj.verbose = verbose


@cli.command()
def version() -> None:
    """Print the PDO version."""
    console.print(f"pdo [bold cyan]{__version__}[/bold cyan]")
