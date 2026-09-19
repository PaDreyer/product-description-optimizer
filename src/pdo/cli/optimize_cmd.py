"""``pdo optimize`` command — trigger optimization on the daemon."""

from __future__ import annotations

import time

import click

from pdo.cli.common import global_options


@click.command()
@click.option("--watch", "-w", is_flag=True, help="Poll for progress until done.")
@click.option(
    "--optimizer",
    "-o",
    "optimizer_name",
    default=None,
    help="Explicitly choose backend (openai, gemini, zhipuai, local_llm, dummy).",
)
@global_options()
@click.pass_context
def optimize(ctx: click.Context, *, watch: bool, optimizer_name: str | None) -> None:
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
            err = f"Unknown optimizer: {optimizer_name}. Available: {', '.join(known)}"
            ctx.obj.out.result(
                success=False,
                error=err,
                msg=(
                    f"[red]✗[/red] Unknown optimizer: [bold]{optimizer_name}[/bold]. "
                    f"Available: {', '.join(known)}"
                ),
            )
            raise SystemExit(1)

    payload: dict[str, str] = {}
    if optimizer_name:
        payload["optimizer"] = optimizer_name

    try:
        resp = send_command("optimize", payload=payload or None)
        ctx.obj.out.result(
            success=resp.success, error=resp.error, msg="[green]✓[/green] Optimization started"
        )

        if not resp.success or ctx.obj.json_output:
            return

        if watch:
            _watch_progress()
    except DaemonNotRunningError as exc:
        ctx.obj.out.result(success=False, error=str(exc))
        raise SystemExit(1) from exc


def _watch_progress() -> None:
    """Poll the daemon for status updates until optimization finishes."""
    from rich.console import Console

    from pdo.cli.client import send_command

    console = Console()

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
                status.update(f"[bold cyan]Optimizing…[/bold cyan] {current}/{total} ({pct}%)")

            stage = data.get("stage", "idle")
            busy = data.get("busy", False)
            if stage != "optimizing" and not busy:
                break

    console.print(f"[green]✓[/green] Done — {done} optimized, {error} errors")
