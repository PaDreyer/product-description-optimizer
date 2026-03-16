"""``pdo import`` command — import a CSV file into the database."""

from __future__ import annotations

from pathlib import Path

import click

from pdo.cli.common import global_options, run_with_spinner


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
@click.option("--limit", "-l", type=int, help="Limit the number of products to import.")
@global_options()
@click.pass_context
def import_cmd(
    ctx: click.Context, file: Path, mapping: tuple[str, ...], delimiter: str, limit: int | None
) -> None:
    """Import a CSV file into the database.

    Each --mapping / -m flag maps a CSV column to one of three roles:
    ``product_id``, ``description``, or ``context``.

    Example:

        pdo import products.csv -m product_id:ProduktID -m description:Beschreibung
    """
    from pdo.cli.client import send_command
    from pdo.exceptions import DaemonNotRunningError

    if not mapping:
        err = "At least one --mapping is required (e.g. -m description:Beschreibung)"
        ctx.obj.out.result(success=False, error=err)
        raise SystemExit(1)

    column_mappings = []
    for m in mapping:
        if ":" not in m:
            err = f"Invalid mapping format: {m!r} (expected ROLE:COLUMN)"
            ctx.obj.out.result(success=False, error=err)
            raise SystemExit(1)
        role, col = m.split(":", 1)
        if role not in {"product_id", "description", "context"}:
            err = f"Unknown role: {role!r} (use product_id, description, or context)"
            ctx.obj.out.result(success=False, error=err)
            raise SystemExit(1)
        column_mappings.append({"role": role, "csv_column_name": col, "display_name": col})

    payload = {
        "csv_path": str(file.resolve()),
        "column_mappings": column_mappings,
        "delimiter": delimiter,
        "limit": limit,
    }

    try:
        resp = run_with_spinner(
            "[bold cyan]Importing…[/bold cyan]",
            lambda: send_command("import", payload),
            json_output=ctx.obj.json_output,
        )
        ctx.obj.out.result(
            success=resp.success,
            data=resp.data if resp.success else dict(),
            error=resp.error,
            msg=(
                f"[green]✓[/green] "
                f"{resp.data.get('message', 'Import started') if resp.success else ''}"
            ),
        )
    except DaemonNotRunningError as exc:
        ctx.obj.out.result(success=False, error=str(exc))
        raise SystemExit(1) from exc
