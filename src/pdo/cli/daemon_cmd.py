"""``pdo daemon`` command group — start, stop, and check the daemon."""

from __future__ import annotations

import sys

import click

from pdo.cli.common import global_options
from pdo.config import load_config
from pdo.daemon.lifecycle import (
    clean_stale_runtime,
    lifecycle_lock,
    stop_process,
)
from pdo.daemon.lifecycle import (
    stop_daemon as stop_shared_daemon,
)
from pdo.daemon.pid import is_daemon_running
from pdo.exceptions import PdoError


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

    from pdo.daemon.server import DaemonServer

    def report_started() -> None:
        ctx.obj.out.result(success=True, status="running", msg="[green]Daemon started.[/green]")

    if not foreground:
        from pdo.daemon.launcher import ensure_daemon_running

        try:
            ensure_daemon_running(config)
        except (RuntimeError, OSError, PdoError) as exc:
            ctx.obj.out.result(success=False, error=str(exc))
            sys.exit(1)
        report_started()
        return

    try:
        DaemonServer(config=config).start(on_ready=report_started)
    except (PdoError, OSError) as exc:
        ctx.obj.out.result(success=False, error=str(exc))
        sys.exit(1)


@daemon.command()
@click.option(
    "--force", is_flag=True, help="Stop the daemon process and clean stale runtime files."
)
@global_options()
@click.pass_context
def stop(ctx: click.Context, *, force: bool) -> None:
    """Stop the running daemon."""
    config = load_config()
    if force:
        try:
            with lifecycle_lock(config):
                stopped = stop_process(config, timeout=10.0, force=True)
                clean_stale_runtime(config)
        except (RuntimeError, OSError, PdoError) as exc:
            ctx.obj.out.result(success=False, error=str(exc))
            sys.exit(1)
        message = (
            "Daemon stopped and runtime files cleaned."
            if stopped
            else "Stale runtime files cleaned."
        )
        ctx.obj.out.result(success=True, msg=f"[green]{message}[/green]")
        return

    try:
        stopped = stop_shared_daemon(config)
    except (RuntimeError, OSError, PdoError) as exc:
        ctx.obj.out.result(
            success=False,
            error=(f"{exc} Try using 'pdo daemon stop --force' or 'pdo daemon repair'."),
        )
        sys.exit(1)
    if stopped:
        ctx.obj.out.result(success=True, msg="[green]Daemon stopped.[/green]")
    else:
        if ctx.obj.json_output:
            ctx.obj.out.result(success=False, error="Daemon is not running.")
        else:
            ctx.obj.out.print("[yellow]Daemon is not running.[/yellow]")


@daemon.command()
@global_options()
@click.pass_context
def repair(ctx: click.Context) -> None:
    """Stop an unresponsive daemon, then clean stale runtime files safely."""
    config = load_config()
    try:
        with lifecycle_lock(config):
            stopped = stop_process(config, timeout=10.0, force=True)
            clean_stale_runtime(config)
    except (RuntimeError, OSError, PdoError) as exc:
        ctx.obj.out.result(success=False, error=str(exc))
        sys.exit(1)
    message = (
        "Daemon stopped and runtime files repaired." if stopped else "Stale runtime files cleaned."
    )
    ctx.obj.out.result(success=True, msg=f"[green]{message}[/green]")


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
