"""``pdo optimize`` command — trigger optimization on the daemon."""

from __future__ import annotations

import time

import click
from rich.console import Console

console = Console()


@click.command()
@click.option("--watch", "-w", is_flag=True, help="Poll for progress until done.")
@click.option(
    "--optimizer",
    "-o",
    "optimizer_name",
    default=None,
    help="Optimizer backend to use (e.g. gemini, dummy). Default: auto-detect.",
)
@click.option(
    "--api-key",
    default=None,
    help="API key for the optimizer (alternative to GEMINI_API_KEY env var).",
)
def optimize(*, watch: bool, optimizer_name: str | None, api_key: str | None) -> None:
    """Start optimizing imported products.

    Use --watch to see a live progress display until optimization completes.
    Use --optimizer to choose a specific backend (see: pdo optimizer list).
    """
    from pdo.cli.client import send_command
    from pdo.exceptions import DaemonNotRunningError

    # Validate the optimizer name early (before sending to daemon)
    if optimizer_name is not None:
        from pdo.core.registry import list_optimizers

        known = [o.name for o in list_optimizers()]
        if optimizer_name not in known:
            console.print(
                f"[red]✗[/red] Unknown optimizer: [bold]{optimizer_name}[/bold]. "
                f"Available: {', '.join(known)}"
            )
            raise SystemExit(1)

    payload: dict[str, str] = {}
    if optimizer_name:
        payload["optimizer"] = optimizer_name
    if api_key:
        payload["api_key"] = api_key

    try:
        resp = send_command("optimize", payload=payload or None)
        if not resp.success:
            console.print(f"[red]✗[/red] {resp.error}")
            return

        console.print("[green]✓[/green] Optimization started")

        if watch:
            _watch_progress()
    except DaemonNotRunningError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1) from exc


def _watch_progress() -> None:
    """Poll the daemon for status updates until optimization finishes."""
    from pdo.cli.client import send_command

    with console.status("[bold cyan]Optimizing…[/bold cyan]") as status:
        while True:
            time.sleep(1)
            resp = send_command("status")
            if not resp.success:
                console.print(f"[red]Error polling:[/red] {resp.error}")
                break

            data = resp.data
            progress = data.get("progress", {})
            total = progress.get("total", 0)
            done = progress.get("done", 0)
            error = progress.get("error", 0)
            current = done + error

            if total > 0:
                pct = int(current / total * 100)
                status.update(
                    f"[bold cyan]Optimizing…[/bold cyan] {current}/{total} ({pct}%)"
                )

            stage = data.get("stage", "idle")
            busy = data.get("busy", False)
            if stage != "optimizing" and not busy:
                break

    console.print(f"[green]✓[/green] Done — {done} optimized, {error} errors")
