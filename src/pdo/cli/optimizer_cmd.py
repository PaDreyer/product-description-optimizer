"""``pdo optimizer`` command group — discover and inspect optimizer backends."""

from __future__ import annotations

import click
from rich.console import Console

console = Console()


@click.group()
def optimizer() -> None:
    """Manage optimizer backends."""


@optimizer.command("list")
def list_cmd() -> None:
    """List available optimizer backends."""
    from pdo.core.registry import get_default_optimizer_name, list_optimizers

    optimizers = list_optimizers()
    default = get_default_optimizer_name()

    console.print("\n[bold]Available optimizers:[/bold]\n")
    for opt in optimizers:
        if opt.available:
            icon = "[green]●[/green]"
            suffix = ""
        else:
            icon = "[dim]○[/dim]"
            suffix = f"  [dim]({opt.reason})[/dim]"
        active = "  [cyan]← active[/cyan]" if opt.name == default else ""
        console.print(f"  {icon} [bold]{opt.name:10s}[/bold] {opt.description}{suffix}{active}")

    console.print(f"\n  Active: [bold cyan]{default}[/bold cyan]\n")
