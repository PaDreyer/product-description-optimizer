"""Root CLI group for the ``pdo`` command.

This module defines the top-level Click group and the global options
(``--json``, ``--verbose``) that all subcommands inherit.
"""

from __future__ import annotations

import click
from rich.console import Console

from pdo import __version__

console = Console()


class _CliContext:
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
    ctx.ensure_object(_CliContext)
    ctx.obj.json_output = json_output
    ctx.obj.verbose = verbose


# ── Simple top-level commands ────────────────────────────────────────


@cli.command()
def version() -> None:
    """Print the PDO version."""
    console.print(f"pdo [bold cyan]{__version__}[/bold cyan]")


@cli.command()
def status() -> None:
    """Show current pipeline status and progress."""
    from pdo.cli.client import send_command
    from pdo.exceptions import DaemonNotRunningError

    try:
        resp = send_command("status")
        if not resp.success:
            console.print(f"[red]Error:[/red] {resp.error}")
            return

        data = resp.data
        stage = data.get("stage", "unknown")
        progress = data.get("progress", {})
        total = progress.get("total", 0)
        done = progress.get("done", 0)
        error = progress.get("error", 0)
        pending = progress.get("pending", 0)

        stage_colors = {
            "idle": "dim", "importing": "cyan", "optimizing": "yellow",
            "exporting": "blue", "done": "green",
        }
        color = stage_colors.get(stage, "white")

        console.print(f"Stage:    [{color}]{stage}[/{color}]")
        console.print(f"Total:    {total}")
        console.print(f"Done:     [green]{done}[/green]")
        console.print(f"Pending:  {pending}")
        console.print(f"Errors:   [red]{error}[/red]")

        if total > 0:
            pct = int((done + error) / total * 100)
            console.print(f"Progress: {pct}%")

        if data.get("paused"):
            console.print("[yellow]⏸  Paused[/yellow]")
    except DaemonNotRunningError as exc:
        console.print(f"[red]Error:[/red] {exc}")


@cli.command()
def pause() -> None:
    """Pause the current optimization."""
    from pdo.cli.client import send_command
    from pdo.exceptions import DaemonNotRunningError

    try:
        resp = send_command("pause")
        if resp.success:
            console.print("[yellow]⏸  Paused[/yellow]")
        else:
            console.print(f"[red]Error:[/red] {resp.error}")
    except DaemonNotRunningError as exc:
        console.print(f"[red]Error:[/red] {exc}")


@cli.command()
def resume() -> None:
    """Resume a paused optimization."""
    from pdo.cli.client import send_command
    from pdo.exceptions import DaemonNotRunningError

    try:
        resp = send_command("resume")
        if resp.success:
            console.print("[green]▶  Resumed[/green]")
        else:
            console.print(f"[red]Error:[/red] {resp.error}")
    except DaemonNotRunningError as exc:
        console.print(f"[red]Error:[/red] {exc}")


@cli.command()
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt.")
def reset(*, yes: bool) -> None:
    """Reset the database (deletes all products and state)."""
    from pdo.cli.client import send_command
    from pdo.exceptions import DaemonNotRunningError

    if not yes and not click.confirm("This will delete all data. Continue?"):
        console.print("[dim]Aborted.[/dim]")
        return

    try:
        resp = send_command("reset")
        if resp.success:
            console.print("[green]✓[/green] Database reset")
        else:
            console.print(f"[red]Error:[/red] {resp.error}")
    except DaemonNotRunningError as exc:
        console.print(f"[red]Error:[/red] {exc}")


# ── Register subcommand groups and commands ──────────────────────────

from pdo.cli.daemon_cmd import daemon  # noqa: E402
from pdo.cli.export_cmd import export  # noqa: E402
from pdo.cli.import_cmd import import_cmd  # noqa: E402
from pdo.cli.logs_cmd import logs  # noqa: E402
from pdo.cli.optimize_cmd import optimize  # noqa: E402

cli.add_command(daemon)
cli.add_command(import_cmd)
cli.add_command(optimize)
cli.add_command(export)
cli.add_command(logs)
