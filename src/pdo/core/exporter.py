"""CSV exporter — writes optimized products back to a CSV file.

Reconstructs original CSV columns from the ``raw_data`` JSON blob and
appends the ``optimized_description`` and ``status`` columns.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pdo.core.db import Database


@dataclass(frozen=True)
class ExportResult:
    """Summary returned after a CSV export."""

    total_exported: int = 0
    output_path: Path = Path()


def export_csv(
    db: Database,
    output_path: Path,
    *,
    include_errors: bool = False,
    delimiter: str = ";",
    encoding: str = "utf-8",
) -> ExportResult:
    """Export products from the database to a CSV file.

    Args:
        db: An initialised :class:`Database` instance.
        output_path: Destination file path.
        include_errors: If *True*, also export products with status ``error``.
        delimiter: CSV field delimiter (defaults to ``";"`` to match import).
        encoding: Output file encoding.

    Returns:
        An :class:`ExportResult` with the number of rows exported and the
        output path.
    """
    db.set_pipeline_state("exporting")

    # Gather products to export
    products = db.get_all_products(status="done")
    if include_errors:
        products.extend(db.get_all_products(status="error"))
        products.sort(key=lambda p: p["id"])

    if not products:
        db.set_pipeline_state("done")
        return ExportResult(total_exported=0, output_path=output_path)

    # Build header from the first product's raw_data keys + extra columns
    first_raw = _parse_raw_data(products[0].get("raw_data"))
    original_headers = list(first_raw.keys())
    extra_headers = ["optimized_description", "status"]
    all_headers = original_headers + extra_headers

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", newline="", encoding=encoding) as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=all_headers,
            delimiter=delimiter,
            extrasaction="ignore",
        )
        writer.writeheader()

        for product in products:
            raw = _parse_raw_data(product.get("raw_data"))
            row: dict[str, Any] = {**raw}
            row["optimized_description"] = product.get("optimized_description", "")
            row["status"] = product.get("status", "")
            writer.writerow(row)

    db.set_pipeline_state("done")

    return ExportResult(
        total_exported=len(products),
        output_path=output_path,
    )


# ── Private helpers ──────────────────────────────────────────────────────


def _parse_raw_data(raw_data: Any) -> dict[str, str]:
    """Ensure raw_data is a dict (it may already be deserialized or still JSON)."""
    if isinstance(raw_data, dict):
        return raw_data
    if isinstance(raw_data, str):
        try:
            return json.loads(raw_data)
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}
