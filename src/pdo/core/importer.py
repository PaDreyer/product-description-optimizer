"""CSV import and source-data correction with persisted column mappings.

The importer is deliberately encoding-flexible and delimiter-aware.  Column
mappings (which CSV header maps to product-id, description, context, etc.)
are provided at import time and persisted in the database for later stages.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pdo.core.csv_format import CsvFormat, detect_format, read_encoding
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
    limit: int | None = None,
    format_: CsvFormat | None = None,
) -> ImportResult:
    """Import a CSV file into the database.

    Args:
        db: An initialised :class:`Database` instance.
        csv_path: Path to the CSV file to import.
        column_mappings: List of :class:`ColumnMapping` defining which CSV
            columns map to ``product_id``, ``description``, and ``context``.
        delimiter: CSV field delimiter (defaults to ``";"``).
        encoding: Explicit read codec. When *None*, use the supplied format or
            detect UTF-8, UTF-16 LE/BE, or CP1252, including supported BOMs.
        limit: Maximum number of source data rows to read, including skipped rows.
        format_: Complete CSV encoding and dialect. When absent, use detected
            encoding but parse with the explicit delimiter and default CSV quoting.

    Returns:
        An :class:`ImportResult` summarising what happened.

    Raises:
        ImportDataError: If the file is missing, empty, or the required
            columns are not present in the header.
    """
    csv_path = Path(csv_path)
    if not csv_path.is_file():
        raise ImportDataError(f"CSV file not found: {csv_path}")

    if csv_path.stat().st_size == 0:
        raise ImportDataError(f"CSV file is empty: {csv_path}")
    detected = format_ or detect_format(csv_path)
    file_encoding = encoding or read_encoding(detected)
    parse_options = detected.reader_kwargs() if format_ else {"delimiter": delimiter}

    # --- Validate mappings ------------------------------------------------
    id_cols = [m for m in column_mappings if m.role == "product_id"]
    desc_cols = [m for m in column_mappings if m.role == "description"]
    if not desc_cols:
        raise ImportDataError("At least one column mapping with role 'description' is required.")
    errors: list[str] = []
    batch: list[dict[str, Any]] = []
    imported = 0
    total = 0
    context_mappings = [m for m in column_mappings if m.role == "context"]

    with csv_path.open(encoding=file_encoding, newline="") as stream:
        reader = csv.DictReader(stream, **parse_options)
        headers = reader.fieldnames or []
        if not headers:
            raise ImportDataError("CSV has no header row.")
        _validate_columns_exist(column_mappings, headers)
        if len(set(headers)) != len(headers) or any(not h.strip() for h in headers):
            raise ImportDataError("CSV column names must be unique and nonempty.")
        stored_format = detected.to_dict()
        stored_format["delimiter"] = parse_options["delimiter"]
        db.set_metadata("source_format", stored_format)
        db.set_metadata("source_headers", headers)

        db.set_column_mappings(
            [
                {
                    "role": m.role,
                    "csv_column_name": m.csv_column_name,
                    "display_name": m.display_name,
                }
                for m in column_mappings
            ]
        )
        db.set_pipeline_state("importing", source_file=str(csv_path))

        for row_number, row in enumerate(reader, start=1):
            if limit is not None and row_number > limit:
                break
            total = row_number
            try:
                batch.append(
                    _build_product_dict(
                        row_number=row_number,
                        row=row,
                        id_cols=id_cols,
                        desc_cols=desc_cols,
                        context_mappings=context_mappings,
                    )
                )
            except Exception as exc:
                errors.append(f"Row {row_number}: {exc}")
            if len(batch) >= 500:
                imported += db.insert_products(batch)
                batch.clear()

    if batch:
        imported += db.insert_products(batch)
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


def _detect_encoding(path: Path) -> str:
    """Validate UTF-8 in bounded chunks, falling back to CP1252."""
    return read_encoding(detect_format(path))


def import_corrections(db: Database, path: Path, format_: CsvFormat) -> int:
    """Validate an entire correction CSV before atomically updating failed products.

    Args:
        db: Active batch database.
        path: CSV containing only corrected source rows.
        format_: Detected or explicitly selected source dialect.

    Returns:
        Number of corrected products; their retry remains an explicit action.

    Raises:
        ImportDataError: For invalid mappings, duplicate IDs, or incomplete rows.
    """
    mappings = [ColumnMapping(**m) for m in db.get_column_mappings()]
    id_cols = [m for m in mappings if m.role == "product_id"]
    if len(id_cols) != 1:
        raise ImportDataError("Corrections require exactly one unique product ID column.")
    products = []
    with path.open(encoding=read_encoding(format_), newline="") as stream:
        reader = csv.DictReader(stream, **format_.reader_kwargs(), strict=True)
        headers = reader.fieldnames or []
        if headers != db.get_metadata("source_headers", headers):
            raise ImportDataError("The correction file must contain the same original columns.")
        _validate_columns_exist(mappings, headers)
        for number, row in enumerate(reader, 1):
            if None in row or any(value is None for value in row.values()):
                raise ImportDataError(f"Incomplete CSV row {number}.")
            products.append(
                _build_product_dict(
                    row_number=number,
                    row=row,
                    id_cols=id_cols,
                    desc_cols=[m for m in mappings if m.role == "description"],
                    context_mappings=[m for m in mappings if m.role == "context"],
                )
            )
    if not products:
        raise ImportDataError("The correction file contains no products.")
    return db.apply_corrections(products)


def _validate_columns_exist(
    mappings: list[ColumnMapping],
    headers: list[str],
) -> None:
    """Raise if any mapped column name is not in the CSV headers."""
    header_set = set(headers)
    missing = [m.csv_column_name for m in mappings if m.csv_column_name not in header_set]
    if missing:
        raise ImportDataError(f"CSV is missing the following mapped columns: {', '.join(missing)}")


def _build_product_dict(
    *,
    row_number: int,
    row: dict[str, str],
    id_cols: list[ColumnMapping],
    desc_cols: list[ColumnMapping],
    context_mappings: list[ColumnMapping],
) -> dict[str, Any]:
    """Transform a single CSV row dict into the shape expected by ``db.insert_products``."""
    product_id_value = (
        " | ".join(row.get(m.csv_column_name, "") for m in id_cols) if id_cols else ""
    )

    description_parts = [row.get(m.csv_column_name, "") for m in desc_cols]
    original_description = "\n\n".join(part for part in description_parts if part)

    context_data: dict[str, str] = {}
    for m in context_mappings:
        val = row.get(m.csv_column_name, "")
        if val:
            context_data[m.csv_column_name] = val

    return {
        "source_row_number": row_number,
        "raw_data": dict(row),
        "product_id_value": product_id_value,
        "original_description": original_description,
        "context_data": context_data if context_data else None,
    }
