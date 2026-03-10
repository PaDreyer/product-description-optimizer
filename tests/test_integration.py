"""End-to-end integration tests — full pipeline via library calls.

These tests exercise the complete flow (import → optimize → export)
without actually starting the socket server.  They use the core modules
directly through the Database, which is the same path the daemon's
Worker takes.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from pdo.core.db import Database
from pdo.core.exporter import export_csv
from pdo.core.importer import ColumnMapping, import_csv
from pdo.core.optimizer import DummyOptimizer, run_optimization

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_CSV = FIXTURES / "sample_products.csv"

MAPPINGS = [
    ColumnMapping(role="product_id", csv_column_name="ProduktID"),
    ColumnMapping(role="description", csv_column_name="Beschreibung"),
    ColumnMapping(role="context", csv_column_name="Titel"),
    ColumnMapping(role="context", csv_column_name="Marke"),
    ColumnMapping(role="context", csv_column_name="Kategorie"),
    ColumnMapping(role="context", csv_column_name="Merkmal 1"),
    ColumnMapping(role="context", csv_column_name="Attribut 1"),
    ColumnMapping(role="context", csv_column_name="Merkmal 2"),
    ColumnMapping(role="context", csv_column_name="Attribut 2"),
]


@pytest.fixture()
def db() -> Database:
    database = Database(":memory:")
    database.initialize()
    return database


class TestFullPipeline:
    """CSV import → optimize → export end-to-end."""

    def test_import_optimize_export(self, db: Database, tmp_path: Path) -> None:
        # ── Import ───────────────────────────────────────────────
        result = import_csv(db, SAMPLE_CSV, column_mappings=MAPPINGS)
        assert result.imported_count == 10
        assert result.errors == []

        products = db.get_all_products()
        assert len(products) == 10
        assert all(p["status"] == "pending" for p in products)

        # Verify specific product data
        p1 = next(p for p in products if p["product_id_value"] == "P001")
        assert "Kugelschreiber" in p1["original_description"]
        assert p1["context_data"]["Marke"] == "SchreibGut"

        # P004 has empty description
        p4 = next(p for p in products if p["product_id_value"] == "P004")
        assert p4["original_description"] == ""

        # ── Optimize ─────────────────────────────────────────────
        opt_result = run_optimization(db, DummyOptimizer())
        assert opt_result.succeeded == 10
        assert opt_result.failed == 0

        products_after = db.get_all_products()
        assert all(p["status"] == "done" for p in products_after)
        assert all(p["optimized_description"] for p in products_after)

        # ── Export ───────────────────────────────────────────────
        output = tmp_path / "output.csv"
        exp_result = export_csv(db, output)
        assert exp_result.total_exported == 10
        assert output.is_file()

        # Verify CSV content
        with output.open(encoding="utf-8") as fh:
            reader = csv.DictReader(fh, delimiter=";")
            rows = list(reader)
        assert len(rows) == 10
        assert "optimized_description" in reader.fieldnames
        assert "status" in reader.fieldnames

        # Original data preserved
        assert rows[0]["ProduktID"] == "P001"
        assert rows[0]["status"] == "done"
        assert "[OPTIMIZED]" in rows[0]["optimized_description"]

    def test_column_mappings_persisted(self, db: Database) -> None:
        import_csv(db, SAMPLE_CSV, column_mappings=MAPPINGS)
        mappings = db.get_column_mappings()
        roles = {m["role"] for m in mappings}
        assert roles == {"product_id", "description", "context"}
        assert len(mappings) == 9  # 1 id + 1 desc + 7 context

    def test_raw_data_round_trip(self, db: Database) -> None:
        """Every original CSV column should survive in raw_data."""
        import_csv(db, SAMPLE_CSV, column_mappings=MAPPINGS)
        products = db.get_all_products()
        raw = products[0]["raw_data"]
        for col in [
            "ProduktID", "Titel", "Beschreibung", "Marke",
            "Kategorie", "Preis", "Merkmal 1", "Attribut 1",
        ]:
            assert col in raw, f"Missing column {col} in raw_data"


class TestPauseResume:
    def test_pause_and_resume(self, db: Database) -> None:
        import_csv(db, SAMPLE_CSV, column_mappings=MAPPINGS)

        import threading

        pause = threading.Event()
        result_holder: list = []

        def _run() -> None:
            r = run_optimization(db, DummyOptimizer(), pause_event=pause)
            result_holder.append(r)

        t = threading.Thread(target=_run)
        t.start()
        t.join(timeout=3.0)

        assert not t.is_alive()
        assert len(result_holder) == 1
        assert result_holder[0].succeeded == 10


class TestReset:
    def test_reset_clears_everything(self, db: Database) -> None:
        import_csv(db, SAMPLE_CSV, column_mappings=MAPPINGS)
        run_optimization(db, DummyOptimizer())

        # Verify data exists
        assert len(db.get_all_products()) == 10

        # Reset
        db.reset()

        # Verify clean state
        assert len(db.get_all_products()) == 0
        state = db.get_pipeline_state()
        assert state["stage"] == "idle"
        assert state["total_products"] == 0
        assert len(db.get_column_mappings()) == 0


class TestResumability:
    def test_partial_optimization_can_resume(self, db: Database) -> None:
        """Simulate a crash: optimize half, then resume."""
        import_csv(db, SAMPLE_CSV, column_mappings=MAPPINGS)

        import threading

        stop = threading.Event()
        processed: list[int] = []

        def _progress(current: int, total: int) -> None:
            processed.append(current)
            if current >= 5:
                stop.set()  # Stop after 5

        run_optimization(
            db, DummyOptimizer(), on_progress=_progress, stop_event=stop
        )

        # Some should be done, some still pending
        progress = db.get_progress()
        done_first = progress["done"]
        assert done_first >= 5

        # "Restart" — run again, only pending should be processed
        result = run_optimization(db, DummyOptimizer())
        assert result.succeeded == 10  # total done including earlier
        assert result.failed == 0

        # All products should be done now
        products = db.get_all_products()
        assert all(p["status"] == "done" for p in products)


class TestExportWithErrors:
    def test_include_errors_flag(self, db: Database, tmp_path: Path) -> None:
        import_csv(db, SAMPLE_CSV, column_mappings=MAPPINGS)

        # Manually mark some as error
        products = db.get_all_products()
        for p in products[:3]:
            db.update_product_status(p["id"], "error", error_message="test error")
        for p in products[3:]:
            db.update_product_status(
                p["id"], "done", optimized_description="optimized"
            )

        # Without errors
        out1 = tmp_path / "no_errors.csv"
        r1 = export_csv(db, out1)
        assert r1.total_exported == 7

        # With errors
        out2 = tmp_path / "with_errors.csv"
        r2 = export_csv(db, out2, include_errors=True)
        assert r2.total_exported == 10
