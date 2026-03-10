"""Worker engine — runs pipeline stages in background threads.

The :class:`Worker` holds threading events for pause/resume and stop
signalling, and ensures only one operation runs at a time.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from pdo.core.db import Database
from pdo.core.exporter import export_csv
from pdo.core.importer import ColumnMapping, import_csv
from pdo.core.optimizer import DummyOptimizer, Optimizer, run_optimization

log = logging.getLogger(__name__)


class Worker:
    """Manages pipeline operations in a background thread.

    Only one operation runs at a time — other requests are rejected while busy.
    """

    def __init__(self, db: Database) -> None:
        self._db = db
        self._thread: threading.Thread | None = None
        self._pause_event = threading.Event()
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._last_result: dict[str, Any] = {}

    # ── Public API ───────────────────────────────────────────────────

    @property
    def is_busy(self) -> bool:
        """Return *True* if a worker thread is currently running."""
        return self._thread is not None and self._thread.is_alive()

    def start_import(
        self,
        csv_path: Path,
        column_mappings: list[dict[str, str]],
        *,
        delimiter: str = ";",
    ) -> bool:
        """Run the CSV importer in a worker thread.

        Returns *True* if started, *False* if already busy.
        """
        if self.is_busy:
            return False

        mappings = [
            ColumnMapping(
                role=m["role"],
                csv_column_name=m["csv_column_name"],
                display_name=m.get("display_name", m["csv_column_name"]),
            )
            for m in column_mappings
        ]

        def _run() -> None:
            try:
                result = import_csv(
                    self._db, csv_path, column_mappings=mappings, delimiter=delimiter
                )
                self._last_result = {
                    "total_rows": result.total_rows,
                    "imported_count": result.imported_count,
                    "skipped_count": result.skipped_count,
                    "errors": result.errors,
                }
                log.info("Import complete: %s", self._last_result)
            except Exception:
                log.exception("Import failed")

        return self._start_thread(_run, "import")

    def start_optimization(self) -> bool:
        """Run the optimizer in a worker thread.

        Automatically uses :class:`GeminiOptimizer` if ``GEMINI_API_KEY`` is
        set, otherwise falls back to :class:`DummyOptimizer`.

        Returns *True* if started, *False* if already busy.
        """
        if self.is_busy:
            return False

        self._pause_event.clear()
        self._stop_event.clear()

        optimizer = self._create_optimizer()

        def _run() -> None:
            try:
                result = run_optimization(
                    self._db,
                    optimizer,
                    pause_event=self._pause_event,
                    stop_event=self._stop_event,
                )
                self._last_result = {
                    "total": result.total,
                    "succeeded": result.succeeded,
                    "failed": result.failed,
                    "skipped": result.skipped,
                }
                log.info("Optimization complete: %s", self._last_result)
            except Exception:
                log.exception("Optimization failed")

        return self._start_thread(_run, "optimize")

    def _create_optimizer(self) -> Optimizer:
        """Create the best available optimizer.

        Returns a :class:`GeminiOptimizer` if ``GEMINI_API_KEY`` is set,
        otherwise a :class:`DummyOptimizer`.
        """
        import os

        api_key = os.environ.get("GEMINI_API_KEY", "")
        if api_key:
            try:
                from pdo.core.gemini_optimizer import GeminiOptimizer

                log.info("Using GeminiOptimizer (model: gemini-2.0-flash)")
                return GeminiOptimizer(api_key=api_key)
            except ImportError:
                log.warning(
                    "google-genai not installed. Install with: "
                    "pip install 'pdo[gemini]'. Falling back to DummyOptimizer."
                )
        else:
            log.info("GEMINI_API_KEY not set — using DummyOptimizer")
        return DummyOptimizer()

    def start_export(
        self,
        output_path: Path,
        *,
        include_errors: bool = False,
    ) -> bool:
        """Run the exporter in a worker thread.

        Returns *True* if started, *False* if already busy.
        """
        if self.is_busy:
            return False

        def _run() -> None:
            try:
                result = export_csv(
                    self._db, output_path, include_errors=include_errors
                )
                self._last_result = {
                    "total_exported": result.total_exported,
                    "output_path": str(result.output_path),
                }
                log.info("Export complete: %s", self._last_result)
            except Exception:
                log.exception("Export failed")

        return self._start_thread(_run, "export")

    def pause(self) -> None:
        """Signal the optimizer to pause."""
        self._pause_event.set()
        log.info("Pause requested")

    def resume(self) -> None:
        """Clear the pause signal so the optimizer continues."""
        self._pause_event.clear()
        log.info("Resume requested")

    def stop(self, timeout: float = 10.0) -> None:
        """Signal the worker to stop and wait for the thread to finish."""
        self._stop_event.set()
        self._pause_event.clear()  # unblock if paused
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        log.info("Worker stopped")

    def get_status(self) -> dict[str, Any]:
        """Return a status snapshot."""
        progress = self._db.get_progress()
        pipeline = self._db.get_pipeline_state()
        return {
            "busy": self.is_busy,
            "paused": self._pause_event.is_set(),
            "stage": pipeline.get("stage", "idle"),
            "progress": progress,
            "last_result": self._last_result,
        }

    # ── Private ──────────────────────────────────────────────────────

    def _start_thread(self, target: Any, name: str) -> bool:
        """Start a daemon thread for the given target function."""
        with self._lock:
            if self.is_busy:
                return False
            self._stop_event.clear()
            self._thread = threading.Thread(target=target, name=f"pdo-{name}", daemon=True)
            self._thread.start()
        return True
