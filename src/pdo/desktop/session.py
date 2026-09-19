"""Desktop workflow facade for the shared PDO daemon."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pdo.cli.client import send_command
from pdo.config import PdoConfig, load_config
from pdo.daemon.launcher import ensure_daemon_running
from pdo.daemon.lifecycle import stop_daemon as stop_shared_daemon
from pdo.exceptions import ImportDataError
from pdo.protocol.messages import Response


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
    """Expose daemon operations to one desktop client."""

    def __init__(self, config: PdoConfig | None = None, *, auto_start: bool = True) -> None:
        self.config = config or load_config()
        if auto_start:
            ensure_daemon_running(self.config)

    def _request(self, action: str, payload: dict[str, Any] | None = None) -> Response:
        """Send one request to the running daemon."""
        response = send_command(action, payload, config=self.config)
        if not response.success:
            raise RuntimeError(response.error or f"Daemon request failed: {action}")
        return response

    def status(self) -> dict[str, Any]:
        """Return current stage, progress, and last operation result."""
        return self._request("status").data

    def products(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return a bounded set of products for the preview table."""
        return self._request("products", {"limit": limit}).data["products"]

    def product(self, product_id: int) -> dict[str, Any]:
        """Return bounded detail text for one product."""
        return self._request("product", {"id": product_id}).data["product"]

    def import_file(self, preview: CsvPreview, mappings: list[dict[str, str]]) -> None:
        """Replace the current batch through the daemon CSV importer."""
        if not any(mapping["role"] == "description" for mapping in mappings):
            raise ValueError("Select at least one description column.")
        self._request(
            "import",
            {
                "csv_path": str(preview.path),
                "column_mappings": mappings,
                "delimiter": preview.delimiter,
                "replace_existing": True,
            },
        )

    def optimize(self, backend: str, settings: dict[str, str]) -> None:
        """Save provider settings in the daemon and start optimization."""
        status = self.status()
        if status["progress"]["pending"] == 0:
            raise ValueError("Import a CSV file with pending products first.")
        self._request("optimize", {"optimizer": backend, "settings": settings})
        self.config = load_config(
            config_file=self.config.config_file_path,
            overrides={
                "data_dir": str(self.config.data_dir),
                "log_dir": str(self.config.log_dir),
                "socket_path": str(self.config.socket_path),
            },
        )

    def export_file(self, output_path: Path, include_errors: bool = False) -> None:
        """Start a CSV export through the daemon."""
        self._request(
            "export",
            {"output_path": str(output_path), "include_errors": include_errors},
        )

    def pause(self) -> None:
        """Pause after the currently running product finishes."""
        self._request("pause")

    def resume(self) -> None:
        """Resume a paused optimization."""
        self._request("resume")

    def close(self) -> None:
        """Disconnect this client without stopping the daemon."""

    def stop_daemon(self) -> None:
        """Stop the shared daemon and wait for its process to exit."""
        stop_shared_daemon(self.config)
