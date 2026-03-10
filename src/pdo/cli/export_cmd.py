"""``pdo export`` command — export optimized products to CSV."""

from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console

console = Console()


@click.command()
@click.argument("output_file", type=click.Path(path_type=Path))
@click.option("--include-errors", is_flag=True, help="Include errored products in the export.")
def export(output_file: Path, *, include_errors: bool) -> None:
    """Export optimized products to a CSV file."""
    from pdo.cli.client import send_command
    from pdo.exceptions import DaemonNotRunningError

    payload = {
        "output_path": str(output_file.resolve()),
        "include_errors": include_errors,
    }

    try:
        with console.status("[bold cyan]Exporting…[/bold cyan]"):
            resp = send_command("export", payload)
        if resp.success:
            console.print(f"[green]✓[/green] {resp.data.get('message', 'Export started')}")
        else:
            console.print(f"[red]✗[/red] {resp.error}")
    except DaemonNotRunningError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1) from exc
