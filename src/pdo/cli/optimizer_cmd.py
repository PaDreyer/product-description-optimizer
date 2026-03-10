"""``pdo optimizer`` command group — discover and inspect optimizer backends."""

from __future__ import annotations

import click

from pdo.cli.common import global_options


@click.group()
def optimizer() -> None:
    """Manage optimizer backends."""


@optimizer.command("list")
@global_options()
@click.pass_context
def list_cmd(ctx: click.Context) -> None:
    """List available optimizer backends."""
    from pdo.core.registry import get_default_optimizer_name, list_optimizers

    optimizers = list_optimizers()
    default = get_default_optimizer_name()

    if ctx.obj.json_output:
        opts_data = [
            {
                "name": opt.name,
                "description": opt.description,
                "available": opt.available,
                "reason": opt.reason,
            }
            for opt in optimizers
        ]
        ctx.obj.out.result(success=True, optimizers=opts_data, default=default)
        return

    ctx.obj.out.print("\n[bold]Available optimizers:[/bold]\n")
    for opt in optimizers:
        if opt.available:
            icon = "[green]●[/green]"
            suffix = ""
        else:
            icon = "[dim]○[/dim]"
            suffix = f"  [dim]({opt.reason})[/dim]"
        active = "  [cyan]← active[/cyan]" if opt.name == default else ""
        ctx.obj.out.print(f"  {icon} [bold]{opt.name:10s}[/bold] {opt.description}{suffix}{active}")

    ctx.obj.out.print(f"\n  Active: [bold cyan]{default}[/bold cyan]\n")
