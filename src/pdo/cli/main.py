"""Root CLI group for the ``pdo`` command.

This module defines the top-level Click group and the global options
(``--json``, ``--verbose``) that all subcommands inherit.
"""

from __future__ import annotations

import click
from pathlib import Path

from pdo import __version__

from pdo.cli.common import _CliContext, global_options


@click.group()
@click.option(
    "--config",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Path to a custom config file.",
)
@global_options()
@click.pass_context
def cli(ctx: click.Context, *, config: Path | None) -> None:
    """PDO — Product Description Optimizer.

    A daemon/client CLI for batch-optimizing product descriptions.
    """
    ctx.ensure_object(_CliContext)
    ctx.obj.config_path = config


# ── Simple top-level commands ────────────────────────────────────────


@cli.command()
@global_options()
@click.pass_context
def version(ctx: click.Context) -> None:
    """Print the PDO version."""
    from pdo.cli.client import send_command
    from pdo.exceptions import DaemonNotRunningError

    daemon_version = None
    try:
        resp = send_command("ping")
        if resp.success:
            # We assume the protocol has been upgraded to include server_version.
            daemon_version = getattr(resp, "server_version", "unknown")
        else:
            # If there was a version mismatch during ping, the error message from the
            # server usually contains the version.
            if "Version mismatch" in (resp.error or ""):
                # E.g. "Version mismatch: CLI client is v0.1.0, but daemon is v0.2.0"
                # We can just let the error surface or extract it, 
                # but let's be explicit.
                daemon_version = "mismatch"
    except DaemonNotRunningError:
        daemon_version = "not running"
        
    if ctx.obj.json_output:
        ctx.obj.out.emit_json({"client_version": __version__, "server_version": daemon_version})
        return

    ctx.obj.out.print(f"Client version: [bold cyan]{__version__}[/bold cyan]")
    if daemon_version == "not running":
        ctx.obj.out.print("Daemon version: [dim]not running[/dim]")
    elif daemon_version == "mismatch":
        ctx.obj.out.print("Daemon version: [bold red]version mismatch (check logs/restart)[/bold red]")
    else:
        ctx.obj.out.print(f"Daemon version: [bold green]{daemon_version}[/bold green]")


@cli.command()
@global_options()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show current pipeline status and progress."""
    from pdo.cli.client import send_command
    from pdo.exceptions import DaemonNotRunningError

    try:
        resp = send_command("status")
        if not resp.success:
            ctx.obj.out.result(success=False, error=resp.error)
            return

        data = resp.data
        if ctx.obj.json_output:
            ctx.obj.out.emit_json(data)
            return
            
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

        ctx.obj.out.print(f"Stage:    [{color}]{stage}[/{color}]")
        ctx.obj.out.print(f"Total:    {total}")
        ctx.obj.out.print(f"Done:     [green]{done}[/green]")
        ctx.obj.out.print(f"Pending:  {pending}")
        ctx.obj.out.print(f"Errors:   [red]{error}[/red]")

        if total > 0:
            pct = int((done + error) / total * 100)
            ctx.obj.out.print(f"Progress: {pct}%")

        if data.get("paused"):
            ctx.obj.out.print("[yellow]⏸  Paused[/yellow]")
    except DaemonNotRunningError as exc:
        ctx.obj.out.result(success=False, error=str(exc))


@cli.command()
@global_options()
@click.pass_context
def pause(ctx: click.Context) -> None:
    """Pause the current optimization."""
    from pdo.cli.client import send_command
    from pdo.exceptions import DaemonNotRunningError

    try:
        resp = send_command("pause")
        ctx.obj.out.result(success=resp.success, error=resp.error, msg="[yellow]⏸  Paused[/yellow]")
    except DaemonNotRunningError as exc:
        ctx.obj.out.result(success=False, error=str(exc))


@cli.command()
@global_options()
@click.pass_context
def resume(ctx: click.Context) -> None:
    """Resume a paused optimization."""
    from pdo.cli.client import send_command
    from pdo.exceptions import DaemonNotRunningError

    try:
        resp = send_command("resume")
        ctx.obj.out.result(success=resp.success, error=resp.error, msg="[green]▶  Resumed[/green]")
    except DaemonNotRunningError as exc:
        ctx.obj.out.result(success=False, error=str(exc))


@cli.command()
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt.")
@global_options()
@click.pass_context
def reset(ctx: click.Context, *, yes: bool) -> None:
    """Reset the database — stops any running operation, then clears all data."""
    from pdo.cli.client import send_command
    from pdo.exceptions import DaemonNotRunningError

    if not yes and not ctx.obj.json_output and not click.confirm(
        "This will stop any running operation and delete all data. Continue?"
    ):
        ctx.obj.out.print("[dim]Aborted.[/dim]")
        return

    try:
        from rich.console import Console
        console = Console()
        if not ctx.obj.json_output:
            with console.status("[bold cyan]Resetting…[/bold cyan]"):
                resp = send_command("reset")
        else:
            resp = send_command("reset")
            
        ctx.obj.out.result(
            success=resp.success, 
            error=resp.error, 
            msg="[green]✓[/green] All operations stopped, database reset"
        )
    except DaemonNotRunningError as exc:
        ctx.obj.out.result(success=False, error=str(exc))


# ── Register subcommand groups and commands ──────────────────────────

from pdo.cli.daemon_cmd import daemon  # noqa: E402
from pdo.cli.export_cmd import export  # noqa: E402
from pdo.cli.import_cmd import import_cmd  # noqa: E402
from pdo.cli.logs_cmd import logs  # noqa: E402
from pdo.cli.optimize_cmd import optimize  # noqa: E402
from pdo.cli.optimizer_cmd import optimizer  # noqa: E402
from pdo.cli.config_cmd import config  # noqa: E402

cli.add_command(daemon)
cli.add_command(import_cmd)
cli.add_command(optimize)
cli.add_command(optimizer)
cli.add_command(export)
cli.add_command(logs)
cli.add_command(config)
