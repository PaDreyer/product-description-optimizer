"""Desktop workflow facade built on the existing importer and worker."""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pdo.config import PdoConfig, load_config, save_config_values
from pdo.core.db import Database
from pdo.core.instance_lock import InstanceLock
from pdo.daemon.pid import is_daemon_running
from pdo.daemon.worker import Worker
from pdo.exceptions import ImportDataError


@dataclass(frozen=True)
class CsvPreview:
    """A small CSV sample and its detected format."""

    path: Path
    headers: list[str]
    rows: list[list[str]]
    delimiter: str
    encoding: str


def inspect_csv(path: Path) -> CsvPreview:
    """Read a few rows and detect the delimiter and encoding.

    Args:
        path: CSV file selected by the user.

    Returns:
        Detected format and a small preview.

    Raises:
        ImportDataError: If the file is empty or unreadable.
    """
    if not path.is_file():
        raise ImportDataError(f"CSV file not found: {path}")
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            with path.open(encoding=encoding, newline="") as stream:
                sample = stream.read(8192)
                if not sample.strip():
                    raise ImportDataError("The CSV file is empty.")
                try:
                    delimiter = csv.Sniffer().sniff(sample, delimiters=";,\t|").delimiter
                except csv.Error:
                    delimiter = ";"
                stream.seek(0)
                reader = csv.reader(stream, delimiter=delimiter)
                headers = next(reader, [])
                if not headers or any(not header.strip() for header in headers):
                    raise ImportDataError("The CSV needs a header row with named columns.")
                rows = [row for _, row in zip(range(5), reader, strict=False)]
                return CsvPreview(path, headers, rows, delimiter, encoding)
        except UnicodeDecodeError:
            continue
        except OSError as exc:
            raise ImportDataError(str(exc)) from exc
    raise ImportDataError("Could not decode the CSV file as UTF-8 or CP1252.")


def suggest_role(header: str) -> str:
    """Suggest a mapping role from a common CSV column name.

    Args:
        header: Source column name.

    Returns:
        One of ``product_id``, ``description``, ``context``, or ``ignore``.
    """
    normalized = header.casefold().replace("_", " ").replace("-", " ").strip()
    if normalized in {"id", "sku", "product id", "produkt id", "produktid", "artikelnummer"}:
        return "product_id"
    if any(word in normalized for word in ("beschreibung", "description", "produkttext")):
        return "description"
    if any(
        word in normalized
        for word in (
            "titel",
            "title",
            "name",
            "marke",
            "brand",
            "kategorie",
            "category",
            "merkmal",
            "attribut",
            "feature",
        )
    ):
        return "context"
    return "ignore"


class DesktopSession:
    """Own the database and background operations for one desktop window."""

    def __init__(self, config: PdoConfig | None = None) -> None:
        self.config = config or load_config()
        if os.name != "nt" and is_daemon_running(self.config.data_dir / "daemon.pid"):
            raise RuntimeError("Stop the CLI daemon before opening the desktop application.")
        self.config.data_dir.mkdir(parents=True, exist_ok=True)
        self._instance_lock = InstanceLock(self.config.data_dir / "pdo.lock")
        self._instance_lock.acquire()
        try:
            self.db = Database(self.config.data_dir / "pdo.db")
            self.db.initialize()
            self.db.requeue_processing()
            self.worker = Worker(self.db, self.config)
        except Exception:
            self._instance_lock.release()
            raise

    def status(self) -> dict[str, Any]:
        """Return current stage, progress, and last operation result."""
        return self.worker.get_status()

    def products(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return a bounded set of products for the preview table."""
        return self.db.get_product_preview(limit)

    def import_file(self, preview: CsvPreview, mappings: list[dict[str, str]]) -> None:
        """Replace the current batch and start a CSV import.

        Args:
            preview: Selected CSV file and detected format.
            mappings: Column mapping dictionaries for the importer.

        Raises:
            ValueError: If no description column was selected or a job is active.
        """
        if self.worker.is_busy:
            raise ValueError("Wait for the current task to finish.")
        if not any(mapping["role"] == "description" for mapping in mappings):
            raise ValueError("Select at least one description column.")
        self.worker.reset()
        self.worker.start_import(
            preview.path,
            mappings,
            delimiter=preview.delimiter,
            replace_existing=True,
        )

    def optimize(self, backend: str, settings: dict[str, str]) -> None:
        """Save provider settings and start the selected optimizer.

        Args:
            backend: Registry name of the optimizer.
            settings: Provider options from the desktop form.

        Raises:
            ValueError: If a job is active or there are no pending products.
        """
        if self.worker.is_busy:
            raise ValueError("Wait for the current task to finish.")
        if self.db.get_progress()["pending"] == 0:
            raise ValueError("Import a CSV file with pending products first.")
        values = {"optimizer": backend, **settings}
        save_config_values(self.config.config_file_path, values)
        self.config = load_config(config_file=self.config.config_file_path)
        self.worker = Worker(self.db, self.config)
        self.worker.start_optimization(optimizer_name=backend)

    def export_file(self, output_path: Path, include_errors: bool = False) -> None:
        """Start a CSV export into the chosen path."""
        if self.worker.is_busy:
            raise ValueError("Wait for the current task to finish.")
        if self.db.get_progress()["done"] == 0 and not include_errors:
            raise ValueError("There are no completed products to export.")
        self.worker.start_export(output_path, include_errors=include_errors)

    def pause(self) -> None:
        """Pause after the currently running product finishes."""
        self.worker.pause()

    def resume(self) -> None:
        """Resume a paused optimization."""
        self.worker.resume()

    def close(self) -> None:
        """Stop background work before closing the database."""
        self.worker.stop(timeout=5.0)
        if self.worker.is_busy:
            raise RuntimeError("The current product is still being processed. Try closing again.")
        self.db.close()
        self._instance_lock.release()
