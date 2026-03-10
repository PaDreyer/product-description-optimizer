"""``pdo logs`` command — read the daemon log file."""

from __future__ import annotations

import time
from pathlib import Path

import click

from pdo.cli.common import global_options
from pdo.config import load_config
from pdo.daemon.pid import is_daemon_running


@click.command()
@click.option("--follow", "-f", is_flag=True, help="Tail the log and stream new lines.")
@click.option("--lines", "-n", default=50, type=int, help="Number of lines to show (default: 50).")
@global_options()
@click.pass_context
def logs(ctx: click.Context, *, follow: bool, lines: int) -> None:
    """Display daemon log output.

    This reads the log file directly — the daemon does NOT need to be running.
    """
    if ctx.obj.json_output:
        ctx.obj.out.result(success=False, error="JSON output is not supported for log streaming.")
        return
    config = load_config()
    log_file = config.log_dir / "daemon.log"

    if not log_file.is_file():
        pid_path = config.data_dir / "daemon.pid"
        if is_daemon_running(pid_path):
            ctx.obj.out.print("[yellow]No log file found yet[/yellow] — nothing has been logged.")
        else:
            ctx.obj.out.print("[yellow]No log file found.[/yellow] Has the daemon been started?")
        return

    _print_tail(log_file, lines, ctx.obj.out)

    if follow:
        _follow(log_file, ctx.obj.out)


def _print_tail(path: Path, n: int, out) -> None:
    """Print the last *n* lines of a file."""
    all_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    tail = all_lines[-n:] if len(all_lines) > n else all_lines
    for line in tail:
        out.print(line, highlight=False)


def _follow(path: Path, out) -> None:
    """Tail the file and print new lines until interrupted."""
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            fh.seek(0, 2)  # seek to end
            while True:
                line = fh.readline()
                if line:
                    out.print(line.rstrip(), highlight=False)
                else:
                    time.sleep(0.3)
    except KeyboardInterrupt:
        out.print("\n[dim]Stopped following.[/dim]")
