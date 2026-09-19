from __future__ import annotations

__doc__ = """Atomic, bounded-memory CSV exports using the same serializer as previews."""

import csv
import io
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pdo.core.csv_format import CsvFormat
from pdo.core.db import Database
from pdo.exceptions import ExportError


@dataclass(frozen=True)
class ExportResult:
    """Summary returned after a CSV export."""

    total_exported: int = 0
    output_path: Path = Path()


def export_columns(db: Database, scope: str, first: dict[str, Any]) -> list[str]:
    """Return original columns plus the fields required by the export scope."""
    original = db.get_metadata("source_headers", list(first.get("raw_data", {})))
    extras = (
        []
        if scope == "corrections"
        else (
            ["error_message", "status"]
            if scope == "errors"
            else ["optimized_description", "status"]
        )
    )
    headers = list(original)
    for name in extras:
        candidate = name
        if candidate in headers:
            candidate = f"pdo_{name}"
            suffix = 2
            while candidate in headers:
                candidate = f"pdo_{name}_{suffix}"
                suffix += 1
        headers.append(candidate)
    return headers


def export_row(product: dict[str, Any], scope: str, headers: list[str]) -> dict[str, Any]:
    """Compose a CSV row without modifying the original source values."""
    result = dict(product["raw_data"])
    if scope == "corrections":
        return result
    key = "error_message" if scope == "errors" else "optimized_description"
    result[headers[-2]] = (
        (product.get(key) or "") if key == "error_message" or product["status"] == "done" else ""
    )
    result[headers[-1]] = product["status"]
    return result


def preview_csv(db: Database, format_: CsvFormat, scope: str = "done") -> str:
    """Serialize two actual products and validate their encoding for preview."""
    products = db.export_page(scope, limit=2)
    if not products:
        return "No products for this export scope."
    buffer = io.StringIO(newline="")
    headers = export_columns(db, scope, products[0])
    writer = csv.DictWriter(buffer, fieldnames=headers, **format_.writer_kwargs())
    if format_.header:
        writer.writeheader()
    for product in products:
        writer.writerow(export_row(product, scope, headers))
    text = buffer.getvalue()
    try:
        text.encode(format_.encoding, errors="strict")
    except UnicodeError as exc:
        raise ExportError("The preview contains characters outside the selected encoding.") from exc
    return text[:40_000]


def export_csv(
    db: Database,
    output_path: Path,
    *,
    include_errors: bool = False,
    delimiter: str = ";",
    encoding: str = "utf-8",
    format_: CsvFormat | None = None,
    scope: str | None = None,
) -> ExportResult:
    """Write a complete CSV atomically; a failed export leaves existing files intact.

    Args:
        db: Initialized database.
        output_path: Destination file, distinct from the imported source.
        include_errors: Legacy option including completed and failed rows.
        delimiter: Legacy delimiter setting.
        encoding: Legacy codec setting.
        format_: Complete validated CSV format.
        scope: done, all, completed, errors, or corrections.

    Returns:
        Exported row count and destination path.

    Raises:
        ExportError: If the format, destination, or character encoding is invalid.
    """
    if format_ is None:
        bom = encoding in {"utf-8-sig", "utf-16"}
        codec = {"utf-8-sig": "utf-8", "utf-16": "utf-16-le"}.get(encoding, encoding)
        format_ = CsvFormat(encoding=codec, delimiter=delimiter, bom=bom)
    scope = scope or ("completed" if include_errors else "done")
    output_path = Path(output_path)
    source = db.get_pipeline_state().get("source_file")
    if source and Path(source).resolve() == output_path.resolve():
        raise ExportError("Choose a new output file; the source file is retained.")
    page = db.export_page(scope)
    if not page:
        db.set_pipeline_state("done")
        return ExportResult(output_path=output_path)
    headers = export_columns(db, scope, page[0])
    db.set_pipeline_state("exporting")
    temporary: Path | None = None
    count = 0
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding=format_.encoding,
            errors="strict",
            newline="",
            dir=output_path.parent,
            prefix=".pdo-export-",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            if format_.bom:
                stream.write("\ufeff")
            writer = csv.DictWriter(stream, fieldnames=headers, **format_.writer_kwargs())
            if format_.header:
                writer.writeheader()
            while page:
                for product in page:
                    writer.writerow(export_row(product, scope, headers))
                    count += 1
                page = db.export_page(scope, after_id=page[-1]["id"])
        temporary.replace(output_path)
    except (OSError, UnicodeError, csv.Error, ValueError) as exc:
        raise ExportError(f"CSV export failed: {exc}") from exc
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
        db.set_pipeline_state("idle")
    db.set_pipeline_state("done")
    return ExportResult(count, output_path)
