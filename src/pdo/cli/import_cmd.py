"""``pdo import`` command — import a CSV file into the database."""

from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console

console = Console()


@click.command("import")
@click.argument("file", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--mapping",
    "-m",
    multiple=True,
    help=(
        "Column mapping in ROLE:COLUMN format, e.g. "
        "-m description:Beschreibung -m product_id:ProduktID -m context:Marke"
    ),
)
@click.option("--delimiter", "-d", default=";", help="CSV delimiter (default: ;).")
def import_cmd(file: Path, mapping: tuple[str, ...], delimiter: str) -> None:
    """Import a CSV file into the database.

    Each --mapping / -m flag maps a CSV column to one of three roles:
    ``product_id``, ``description``, or ``context``.

    Example:

        pdo import products.csv -m product_id:ProduktID -m description:Beschreibung
    """
    from pdo.cli.client import send_command
    from pdo.exceptions import DaemonNotRunningError

    if not mapping:
        console.print(
            "[red]Error:[/red] At least one --mapping is required "
            "(e.g. -m description:Beschreibung)"
        )
        raise SystemExit(1)

    column_mappings = []
    for m in mapping:
        if ":" not in m:
            console.print(f"[red]Error:[/red] Invalid mapping format: {m!r} (expected ROLE:COLUMN)")
            raise SystemExit(1)
        role, col = m.split(":", 1)
        if role not in {"product_id", "description", "context"}:
            console.print(
                f"[red]Error:[/red] Unknown role: {role!r}"
                " (use product_id, description, or context)"
            )
            raise SystemExit(1)
        column_mappings.append({"role": role, "csv_column_name": col, "display_name": col})

    payload = {
        "csv_path": str(file.resolve()),
        "column_mappings": column_mappings,
        "delimiter": delimiter,
    }

    try:
        with console.status("[bold cyan]Importing…[/bold cyan]"):
            resp = send_command("import", payload)
        if resp.success:
            console.print(f"[green]✓[/green] {resp.data.get('message', 'Import started')}")
        else:
            console.print(f"[red]✗[/red] {resp.error}")
    except DaemonNotRunningError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1) from exc
