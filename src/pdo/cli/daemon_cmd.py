"""``pdo daemon`` command group — start, stop, and check the daemon."""

from __future__ import annotations

import sys

import click

from pdo.cli.common import global_options
from pdo.config import load_config
from pdo.daemon.pid import is_daemon_running


@click.group()
def daemon() -> None:
    """Manage the PDO daemon process."""


@daemon.command()
@click.option("--foreground", is_flag=True, help="Run in the foreground (debug mode).")
@global_options()
@click.pass_context
def start(ctx: click.Context, *, foreground: bool) -> None:
    """Start the daemon process."""
    config = load_config()
    pid_path = config.data_dir / "daemon.pid"

    if is_daemon_running(pid_path):
        if ctx.obj.json_output:
            ctx.obj.out.result(success=False, error="Daemon is already running.")
        else:
            ctx.obj.out.print("[yellow]Daemon is already running.[/yellow]")
        sys.exit(1)

    from pdo.daemon.server import DaemonServer

    server = DaemonServer(config=config)
    ctx.obj.out.result(success=True, status="starting daemon", msg="[green]Starting daemon …[/green]")
    server.start(foreground=foreground)


@daemon.command()
@global_options()
@click.pass_context
def stop(ctx: click.Context) -> None:
    """Stop the running daemon."""
    from pdo.cli.client import send_command
    from pdo.exceptions import DaemonNotRunningError

    try:
        resp = send_command("stop")
        ctx.obj.out.result(
            success=resp.success, 
            error=resp.error, 
            msg="[green]Daemon is stopping.[/green]"
        )
    except DaemonNotRunningError:
        if ctx.obj.json_output:
            ctx.obj.out.result(success=False, error="Daemon is not running.")
        else:
            ctx.obj.out.print("[yellow]Daemon is not running.[/yellow]")


@daemon.command("status")
@global_options()
@click.pass_context
def daemon_status(ctx: click.Context) -> None:
    """Check whether the daemon is running."""
    config = load_config()
    pid_path = config.data_dir / "daemon.pid"

    if not is_daemon_running(pid_path):
        if ctx.obj.json_output:
            ctx.obj.out.emit_json({"running": False, "responding": False})
        else:
            ctx.obj.out.print("[red]●[/red] Daemon is [bold]stopped[/bold]")
        return

    from pdo.cli.client import send_command
    from pdo.exceptions import DaemonNotRunningError

    try:
        resp = send_command("ping", config=config)
        if ctx.obj.json_output:
            ctx.obj.out.emit_json({"running": True, "responding": resp.success})
            return
            
        if resp.success:
            ctx.obj.out.print("[green]●[/green] Daemon is [bold]running[/bold]")
        else:
            ctx.obj.out.print("[yellow]●[/yellow] Daemon PID exists but not responding")
    except DaemonNotRunningError:
        if ctx.obj.json_output:
            ctx.obj.out.emit_json({"running": True, "responding": False})
        else:
            ctx.obj.out.print("[yellow]●[/yellow] Daemon PID exists but not responding")
