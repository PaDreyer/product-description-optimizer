"""Desktop workflow facade for the shared PDO daemon."""

from __future__ import annotations

import csv
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pdo.cli.client import send_command
from pdo.config import PdoConfig, load_config
from pdo.core.csv_format import CsvFormat, detect_format, read_encoding
from pdo.core.model_discovery import discover_models, discover_openai_models
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
    format: CsvFormat | None = None


def inspect_csv(path: Path) -> CsvPreview:
    """Read a few rows and detect the delimiter and encoding.

    Args:
        path: CSV file selected by the user.

    Returns:
        Detected format and a small preview.

    Raises:
        ImportDataError: If the file is empty or unreadable.
    """
    format_ = detect_format(path)
    try:
        with path.open(encoding=read_encoding(format_), newline="") as stream:
            reader = csv.reader(stream, **format_.reader_kwargs(), strict=True)
            headers = next(reader, [])
            if (
                not headers
                or any(not h.strip() for h in headers)
                or len(set(headers)) != len(headers)
            ):
                raise ImportDataError("CSV column names must be unique and nonempty.")
            rows = [row for _, row in zip(range(5), reader, strict=False)]
            return CsvPreview(
                path, headers, rows, format_.delimiter, read_encoding(format_), format_
            )
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ImportDataError(str(exc)) from exc


def suggest_role(header: str) -> str:
    """Suggest a mapping role from a common CSV column name.

    Args:
        header: Source column name.

    Returns:
        One of ``product_id``, ``description``, ``context``, or ``ignore``.
    """
    normalized = header.casefold().replace("_", " ").replace("-", " ").strip()
    if normalized in {"id", "sku", "product id", "productid", "item number"}:
        return "product_id"
    if "description" in normalized:
        return "description"
    if any(
        word in normalized
        for word in (
            "title",
            "name",
            "brand",
            "category",
            "feature",
        )
    ):
        return "context"
    return "ignore"


class DesktopSession:
    """Expose daemon operations to one desktop client."""

    def __init__(self, config: PdoConfig | None = None, *, auto_start: bool = True) -> None:
        self.config = config or load_config()
        self._closing = threading.Event()
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
                "format": (preview.format or CsvFormat(delimiter=preview.delimiter)).to_dict(),
            },
        )

    def optimize(self, backend: str, settings: dict[str, str]) -> None:
        """Save provider settings in the daemon and start optimization."""
        status = self.status()
        if status["progress"]["pending"] == 0:
            raise ValueError("Import a CSV file with pending products first.")
        self._request("optimize", {"optimizer": backend, "settings": settings})
        self._reload_config()

    def export_file(
        self,
        output_path: Path,
        include_errors: bool = False,
        *,
        format_: CsvFormat | None = None,
        scope: str | None = None,
        remember_format: bool = False,
    ) -> None:
        """Start a CSV export through the daemon."""
        self._request(
            "export",
            {
                "output_path": str(output_path),
                "include_errors": include_errors,
                **({"format": format_.to_dict()} if format_ else {}),
                **({"scope": scope} if scope else {}),
                "remember_format": remember_format,
            },
        )
        if remember_format:
            self._reload_config()

    def product_page(
        self, offset: int = 0, status: str | None = None, search: str = ""
    ) -> dict[str, Any]:
        """Read one product page and its matching total count."""
        return self._request(
            "products", {"offset": offset, "status": status, "search": search}
        ).data

    def retry_errors(self, groups: list[str]) -> None:
        """Retry all products in selected groups, retaining successful results."""
        self._request("optimize", {"retry_groups": groups})

    def import_corrections(self, preview: CsvPreview) -> None:
        """Apply a correction CSV to failed products by unique product ID."""
        self._request(
            "import",
            {
                "csv_path": str(preview.path),
                "corrections": True,
                "format": (preview.format or CsvFormat()).to_dict(),
            },
        )

    def save_settings(self, backend: str, settings: dict[str, str]) -> None:
        """Save provider settings independently of starting a run."""
        self._request("settings", {"optimizer": backend, "settings": settings})
        self._reload_config()

    def _reload_config(self) -> None:
        self.config = load_config(
            config_file=self.config.config_file_path,
            overrides={
                "data_dir": str(self.config.data_dir),
                "log_dir": str(self.config.log_dir),
                "socket_path": str(self.config.socket_path),
            },
        )

    def models(self, address: str) -> list[str]:
        """Discover models from a configured server; call outside the UI thread."""
        return discover_models(address)

    def openai_models(self, api_key: str) -> list[str]:
        """Discover OpenAI text models outside the UI thread using the supplied key."""
        return discover_openai_models(api_key)

    def chatgpt_models(self, *, login: bool = False) -> list[str]:
        """Optionally log in through Codex, then list the subscription's models."""
        from pdo.core.codex_client import CodexClient

        with CodexClient(
            self.config.config_file_path.parent / "codex",
            self.config.options.get("openai.codex_path", "codex"),
            cancel=self._closing,
        ) as client:
            if login:
                client.login()
            return client.models()

    def export_preview(self, format_: CsvFormat, scope: str) -> str:
        """Return a CSV preview using the actual exporter and product data."""
        return self._request("export_preview", {"format": format_.to_dict(), "scope": scope}).data[
            "text"
        ]

    def pause(self) -> None:
        """Pause after the currently running product finishes."""
        self._request("pause")

    def resume(self) -> None:
        """Resume a paused optimization."""
        self._request("resume")

    def close(self) -> None:
        """Disconnect this client without stopping the daemon."""
        self._closing.set()

    def stop_daemon(self) -> None:
        """Stop the shared daemon and wait for its process to exit."""
        stop_shared_daemon(self.config)
