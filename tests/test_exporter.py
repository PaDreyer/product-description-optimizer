"""Tests for the CSV exporter (``pdo.core.exporter``)."""

from __future__ import annotations

import csv
from collections.abc import Iterator
from pathlib import Path

import pytest

from pdo.core.db import Database
from pdo.core.exporter import export_csv
from pdo.core.optimizer import DummyOptimizer, run_optimization


@pytest.fixture()
def db() -> Iterator[Database]:
    with Database(":memory:") as database:
        database.initialize()
        yield database


def _seed_and_optimize(db: Database, count: int = 3) -> None:
    """Insert products and run the dummy optimizer on them."""
    db.insert_products(
        [
            {
                "source_row_number": i + 1,
                "raw_data": {
                    "ProduktID": f"P{i:04d}",
                    "Titel": f"Product {i}",
                    "Beschreibung": f"Description {i}",
                    "Marke": f"Brand{i}",
                },
                "product_id_value": f"P{i:04d}",
                "original_description": f"Description {i}",
                "context_data": {"Marke": f"Brand{i}"},
            }
            for i in range(count)
        ]
    )
    run_optimization(db, DummyOptimizer())


class TestExportValid:
    def test_exports_done_products(self, db: Database, tmp_path: Path) -> None:
        _seed_and_optimize(db, 3)
        output = tmp_path / "out.csv"
        result = export_csv(db, output)
        assert result.total_exported == 3
        assert result.output_path == output
        assert output.is_file()

    def test_csv_has_original_plus_extra_columns(self, db: Database, tmp_path: Path) -> None:
        _seed_and_optimize(db, 2)
        output = tmp_path / "out.csv"
        export_csv(db, output)

        with output.open(encoding="utf-8") as fh:
            reader = csv.DictReader(fh, delimiter=";")
            headers = reader.fieldnames or []
            assert "ProduktID" in headers
            assert "optimized_description" in headers
            assert "status" in headers

    def test_csv_content_correct(self, db: Database, tmp_path: Path) -> None:
        _seed_and_optimize(db, 2)
        output = tmp_path / "out.csv"
        export_csv(db, output)

        with output.open(encoding="utf-8") as fh:
            reader = csv.DictReader(fh, delimiter=";")
            rows = list(reader)
        assert len(rows) == 2
        assert rows[0]["ProduktID"] == "P0000"
        assert rows[0]["status"] == "done"
        assert "[OPTIMIZED]" in rows[0]["optimized_description"]

    def test_export_readable(self, db: Database, tmp_path: Path) -> None:
        """Verify the exported file can be read back."""
        _seed_and_optimize(db, 3)
        output = tmp_path / "out.csv"
        export_csv(db, output)
        text = output.read_text(encoding="utf-8")
        lines = text.strip().splitlines()
        assert len(lines) == 4  # header + 3 rows


class TestExportIncludeErrors:
    def test_includes_error_products(self, db: Database, tmp_path: Path) -> None:
        db.insert_products(
            [
                {
                    "source_row_number": 1,
                    "raw_data": {"ProduktID": "P001", "Beschreibung": "desc"},
                    "product_id_value": "P001",
                    "original_description": "desc",
                    "context_data": None,
                },
                {
                    "source_row_number": 2,
                    "raw_data": {"ProduktID": "P002", "Beschreibung": "desc2"},
                    "product_id_value": "P002",
                    "original_description": "desc2",
                    "context_data": None,
                },
            ]
        )
        # Mark one as done, one as error
        products = db.get_all_products()
        db.update_product_status(products[0]["id"], "done", optimized_description="optimized")
        db.update_product_status(products[1]["id"], "error", error_message="failed")

        output = tmp_path / "out.csv"
        result = export_csv(db, output, include_errors=True)
        assert result.total_exported == 2

    def test_excludes_error_by_default(self, db: Database, tmp_path: Path) -> None:
        db.insert_products(
            [
                {
                    "source_row_number": 1,
                    "raw_data": {"ProduktID": "P001"},
                    "product_id_value": "P001",
                    "original_description": "desc",
                    "context_data": None,
                },
            ]
        )
        products = db.get_all_products()
        db.update_product_status(products[0]["id"], "error", error_message="fail")

        output = tmp_path / "out.csv"
        result = export_csv(db, output)
        assert result.total_exported == 0


class TestExportEmpty:
    def test_no_products_exported(self, db: Database, tmp_path: Path) -> None:
        output = tmp_path / "out.csv"
        result = export_csv(db, output)
        assert result.total_exported == 0

    def test_pipeline_state_set_to_done(self, db: Database, tmp_path: Path) -> None:
        _seed_and_optimize(db, 2)
        output = tmp_path / "out.csv"
        export_csv(db, output)
        state = db.get_pipeline_state()
        assert state["stage"] == "done"
