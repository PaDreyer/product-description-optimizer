"""``pdo daemon`` command group — start, stop, and check the daemon."""

from __future__ import annotations

import sys

import click
from rich.console import Console

from pdo.config import load_config
from pdo.daemon.pid import is_daemon_running

console = Console()


@click.group()
def daemon() -> None:
    """Manage the PDO daemon process."""


@daemon.command()
@click.option("--foreground", is_flag=True, help="Run in the foreground (debug mode).")
def start(*, foreground: bool) -> None:
    """Start the daemon process."""
    config = load_config()
    pid_path = config.data_dir / "daemon.pid"

    if is_daemon_running(pid_path):
        console.print("[yellow]Daemon is already running.[/yellow]")
        sys.exit(1)

    from pdo.daemon.server import DaemonServer

    server = DaemonServer(config=config)
    console.print("[green]Starting daemon …[/green]")
    server.start(foreground=foreground)


@daemon.command()
def stop() -> None:
    """Stop the running daemon."""
    from pdo.cli.client import send_command
    from pdo.exceptions import DaemonNotRunningError

    try:
        resp = send_command("stop")
        if resp.success:
            console.print("[green]Daemon is stopping.[/green]")
        else:
            console.print(f"[red]Error:[/red] {resp.error}")
    except DaemonNotRunningError:
        console.print("[yellow]Daemon is not running.[/yellow]")


@daemon.command("status")
def daemon_status() -> None:
    """Check whether the daemon is running."""
    config = load_config()
    pid_path = config.data_dir / "daemon.pid"

    if not is_daemon_running(pid_path):
        console.print("[red]●[/red] Daemon is [bold]stopped[/bold]")
        return

    from pdo.cli.client import send_command
    from pdo.exceptions import DaemonNotRunningError

    try:
        resp = send_command("ping", config=config)
        if resp.success:
            console.print("[green]●[/green] Daemon is [bold]running[/bold]")
        else:
            console.print("[yellow]●[/yellow] Daemon PID exists but not responding")
    except DaemonNotRunningError:
        console.print("[yellow]●[/yellow] Daemon PID exists but not responding")
