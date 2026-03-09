"""CSV importer — reads a semicolon-delimited CSV into the products table.

The importer is deliberately encoding-flexible and delimiter-aware.  Column
mappings (which CSV header maps to product-id, description, context, etc.)
are provided at import time and persisted in the database for later stages.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pdo.core.db import Database
from pdo.exceptions import ImportDataError


@dataclass(frozen=True)
class ImportResult:
    """Summary returned after a CSV import."""

    total_rows: int = 0
    imported_count: int = 0
    skipped_count: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ColumnMapping:
    """Describes how a CSV column maps to a semantic role."""

    role: str  # "product_id", "description", or "context"
    csv_column_name: str
    display_name: str = ""

    def __post_init__(self) -> None:
        if not self.display_name:
            object.__setattr__(self, "display_name", self.csv_column_name)


def import_csv(
    db: Database,
    csv_path: Path,
    *,
    column_mappings: list[ColumnMapping],
    delimiter: str = ";",
    encoding: str | None = None,
) -> ImportResult:
    """Import a CSV file into the database.

    Args:
        db: An initialised :class:`Database` instance.
        csv_path: Path to the CSV file to import.
        column_mappings: List of :class:`ColumnMapping` defining which CSV
            columns map to ``product_id``, ``description``, and ``context``.
        delimiter: CSV field delimiter (defaults to ``";"``).
        encoding: File encoding.  When *None* the importer tries UTF-8 first,
            then falls back to ``cp1252``.

    Returns:
        An :class:`ImportResult` summarising what happened.

    Raises:
        ImportDataError: If the file is missing, empty, or the required
            columns are not present in the header.
    """
    csv_path = Path(csv_path)
    if not csv_path.is_file():
        raise ImportDataError(f"CSV file not found: {csv_path}")

    text = _read_file(csv_path, encoding)
    if not text.strip():
        raise ImportDataError(f"CSV file is empty: {csv_path}")

    # --- Validate mappings ------------------------------------------------
    id_cols = [m for m in column_mappings if m.role == "product_id"]
    desc_cols = [m for m in column_mappings if m.role == "description"]
    if not desc_cols:
        raise ImportDataError(
            "At least one column mapping with role 'description' is required."
        )

    # --- Parse CSV ---------------------------------------------------------
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    headers = reader.fieldnames or []
    if not headers:
        raise ImportDataError("CSV has no header row.")

    _validate_columns_exist(column_mappings, headers)

    # --- Persist column mappings ------------------------------------------
    db.set_column_mappings([
        {"role": m.role, "csv_column_name": m.csv_column_name, "display_name": m.display_name}
        for m in column_mappings
    ])

    # --- Set pipeline state -----------------------------------------------
    db.set_pipeline_state("importing", source_file=str(csv_path))

    # --- Read rows --------------------------------------------------------
    errors: list[str] = []
    batch: list[dict[str, Any]] = []
    row_num = 0

    for row_num, row in enumerate(reader, start=1):
        try:
            product = _build_product_dict(
                row_number=row_num,
                row=row,
                id_cols=id_cols,
                desc_cols=desc_cols,
                context_mappings=[m for m in column_mappings if m.role == "context"],
            )
            batch.append(product)
        except Exception as exc:
            errors.append(f"Row {row_num}: {exc}")

    # --- Bulk insert ------------------------------------------------------
    imported = 0
    if batch:
        imported = db.insert_products(batch)

    total = row_num
    skipped = total - imported

    db.set_pipeline_state(
        "idle",
        total_products=imported,
        processed_count=0,
    )

    return ImportResult(
        total_rows=total,
        imported_count=imported,
        skipped_count=skipped,
        errors=errors,
    )


# ── Private helpers ──────────────────────────────────────────────────────


def _read_file(path: Path, encoding: str | None) -> str:
    """Read the file, trying UTF-8 first then CP1252 if no encoding given."""
    if encoding:
        return path.read_text(encoding=encoding)

    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="cp1252")


def _validate_columns_exist(
    mappings: list[ColumnMapping],
    headers: list[str],
) -> None:
    """Raise if any mapped column name is not in the CSV headers."""
    header_set = set(headers)
    missing = [m.csv_column_name for m in mappings if m.csv_column_name not in header_set]
    if missing:
        raise ImportDataError(
            f"CSV is missing the following mapped columns: {', '.join(missing)}"
        )


def _build_product_dict(
    *,
    row_number: int,
    row: dict[str, str],
    id_cols: list[ColumnMapping],
    desc_cols: list[ColumnMapping],
    context_mappings: list[ColumnMapping],
) -> dict[str, Any]:
    """Transform a single CSV row dict into the shape expected by ``db.insert_products``."""
    product_id_value = " | ".join(
        row.get(m.csv_column_name, "") for m in id_cols
    ) if id_cols else ""

    description_parts = [row.get(m.csv_column_name, "") for m in desc_cols]
    original_description = "\n\n".join(part for part in description_parts if part)

    context_data: dict[str, str] = {}
    for m in context_mappings:
        val = row.get(m.csv_column_name, "")
        if val:
            context_data[m.csv_column_name] = val

    return {
        "source_row_number": row_number,
        "raw_data": {k: v for k, v in row.items()},
        "product_id_value": product_id_value,
        "original_description": original_description,
        "context_data": context_data if context_data else None,
    }
