"""``pdo export`` command — export optimized products to CSV."""

from __future__ import annotations

from pathlib import Path

import click
from pathlib import Path

from pdo.cli.common import global_options


@click.command()
@click.argument("output_file", type=click.Path(path_type=Path))
@click.option("--include-errors", is_flag=True, help="Include errored products in the export.")
@global_options()
@click.pass_context
def export(ctx: click.Context, output_file: Path, *, include_errors: bool) -> None:
    """Export optimized products to a CSV file."""
    from pdo.cli.client import send_command
    from pdo.exceptions import DaemonNotRunningError

    payload = {
        "output_path": str(output_file.resolve()),
        "include_errors": include_errors,
    }

    try:
        from rich.console import Console
        console = Console()
        if not ctx.obj.json_output:
            with console.status("[bold cyan]Exporting…[/bold cyan]"):
                resp = send_command("export", payload)
        else:
            resp = send_command("export", payload)
            
        ctx.obj.out.result(
            success=resp.success, 
            data=resp.data if resp.success else dict(),
            error=resp.error, 
            msg=f"[green]✓[/green] {resp.data.get('message', 'Export started') if resp.success else ''}"
        )
    except DaemonNotRunningError as exc:
        ctx.obj.out.result(success=False, error=str(exc))
        raise SystemExit(1) from exc
