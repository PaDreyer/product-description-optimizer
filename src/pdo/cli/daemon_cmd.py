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
    ctx.obj.out.result(
        success=True, status="starting daemon", msg="[green]Starting daemon …[/green]"
    )
    server.start(foreground=foreground)


@daemon.command()
@click.option(
    "--force", is_flag=True, help="Force kill the daemon process and remove PID/socket files."
)
@global_options()
@click.pass_context
def stop(ctx: click.Context, *, force: bool) -> None:
    """Stop the running daemon."""
    import signal

    from pdo.cli.client import send_command
    from pdo.daemon.pid import remove_pid, send_signal
    from pdo.exceptions import DaemonNotRunningError

    if force:
        config = load_config()
        pid_path = config.data_dir / "daemon.pid"
        if send_signal(pid_path, signal.SIGTERM):
            ctx.obj.out.result(
                success=True, msg="[green]Daemon force-killed using SIGTERM.[/green]"
            )
        else:
            ctx.obj.out.result(success=False, error="Daemon PID not found or permission denied.")
        # Ensure cleanup
        remove_pid(pid_path)
        config.socket_path.unlink(missing_ok=True)
        return

    try:
        resp = send_command("stop")
        if not resp.success:
            ctx.obj.out.result(
                success=False,
                error=(
                    f"Failed to stop via IPC: {resp.error}. "
                    "Try using 'pdo daemon stop --force' or 'pdo daemon repair'."
                ),
            )
            return

        ctx.obj.out.result(
            success=resp.success, error=resp.error, msg="[green]Daemon is stopping.[/green]"
        )
    except DaemonNotRunningError:
        if ctx.obj.json_output:
            ctx.obj.out.result(success=False, error="Daemon is not running.")
        else:
            ctx.obj.out.print("[yellow]Daemon is not running.[/yellow]")


@daemon.command()
@global_options()
@click.pass_context
def repair(ctx: click.Context) -> None:
    """Repair an unresponsive daemon by forcefully cleaning it up."""
    import signal

    from pdo.daemon.pid import remove_pid, send_signal

    config = load_config()
    pid_path = config.data_dir / "daemon.pid"
    socket_path = config.socket_path

    msgs = ["[yellow]Commencing daemon repair …[/yellow]"]

    # Attempt gentle kill first, then forceful
    killed = False
    if send_signal(pid_path, signal.SIGTERM):
        msgs.append("[green]✓ Sent SIGTERM to stale daemon process.[/green]")
        killed = True
    elif send_signal(pid_path, signal.SIGKILL):
        msgs.append("[green]✓ Sent SIGKILL to stale daemon process.[/green]")
        killed = True

    if not killed:
        msgs.append("[dim]No running daemon process found to kill.[/dim]")

    remove_pid(pid_path)
    socket_path.unlink(missing_ok=True)
    msgs.append("[green]✓ Cleaned up stale PID and socket files.[/green]")
    msgs.append("[bold green]Repair complete. You can now start the daemon.[/bold green]")

    if ctx.obj.json_output:
        ctx.obj.out.result(success=True, msg="Daemon repaired")
    else:
        ctx.obj.out.print("\n".join(msgs))


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
