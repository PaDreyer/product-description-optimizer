"""Tests for the SQLite database layer (``pdo.core.db``)."""

from __future__ import annotations

import pytest

from pdo.core.db import Database


@pytest.fixture()
def db() -> Database:
    """Return an initialised in-memory database."""
    database = Database(":memory:")
    database.initialize()
    return database


# ── Schema initialisation ────────────────────────────────────────────


class TestInitialize:
    def test_initialize_creates_tables(self, db: Database) -> None:
        tables = {
            row[0]
            for row in db._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "products" in tables
        assert "pipeline_state" in tables
        assert "column_mappings" in tables

    def test_initialize_is_idempotent(self, db: Database) -> None:
        """Calling initialize() twice must not raise."""
        db.initialize()
        db.initialize()

    def test_pipeline_state_singleton_seeded(self, db: Database) -> None:
        state = db.get_pipeline_state()
        assert state["id"] == 1
        assert state["stage"] == "idle"
        assert state["total_products"] == 0


# ── Product CRUD ─────────────────────────────────────────────────────


def _sample_products(n: int = 3) -> list[dict]:
    return [
        {
            "source_row_number": i + 1,
            "raw_data": {"col_a": f"val_{i}", "Beschreibung": f"desc {i}"},
            "product_id_value": f"P{i:04d}",
            "original_description": f"Original description {i}",
            "context_data": {"Marke": f"Brand{i}"},
        }
        for i in range(n)
    ]


class TestInsertProducts:
    def test_insert_returns_count(self, db: Database) -> None:
        count = db.insert_products(_sample_products(5))
        assert count == 5

    def test_inserted_products_have_pending_status(self, db: Database) -> None:
        db.insert_products(_sample_products(2))
        products = db.get_all_products()
        assert len(products) == 2
        assert all(p["status"] == "pending" for p in products)

    def test_raw_data_is_deserialized(self, db: Database) -> None:
        db.insert_products(_sample_products(1))
        product = db.get_all_products()[0]
        assert isinstance(product["raw_data"], dict)
        assert product["raw_data"]["col_a"] == "val_0"

    def test_context_data_is_deserialized(self, db: Database) -> None:
        db.insert_products(_sample_products(1))
        product = db.get_all_products()[0]
        assert isinstance(product["context_data"], dict)
        assert product["context_data"]["Marke"] == "Brand0"


class TestGetNextPending:
    def test_returns_none_when_empty(self, db: Database) -> None:
        assert db.get_next_pending() is None

    def test_returns_first_pending(self, db: Database) -> None:
        db.insert_products(_sample_products(3))
        pending = db.get_next_pending()
        assert pending is not None
        assert pending["source_row_number"] == 1

    def test_skips_non_pending(self, db: Database) -> None:
        db.insert_products(_sample_products(3))
        # Mark first product as done
        first = db.get_next_pending()
        db.update_product_status(first["id"], "done", optimized_description="better text")
        next_pending = db.get_next_pending()
        assert next_pending is not None
        assert next_pending["source_row_number"] == 2


# ── Status transitions ───────────────────────────────────────────────


class TestUpdateProductStatus:
    def test_transition_pending_to_processing(self, db: Database) -> None:
        db.insert_products(_sample_products(1))
        product = db.get_next_pending()
        db.update_product_status(product["id"], "processing")
        updated = db.get_all_products()[0]
        assert updated["status"] == "processing"

    def test_transition_processing_to_done(self, db: Database) -> None:
        db.insert_products(_sample_products(1))
        product = db.get_next_pending()
        db.update_product_status(product["id"], "processing")
        db.update_product_status(
            product["id"], "done", optimized_description="Improved description"
        )
        updated = db.get_all_products()[0]
        assert updated["status"] == "done"
        assert updated["optimized_description"] == "Improved description"

    def test_transition_processing_to_error(self, db: Database) -> None:
        db.insert_products(_sample_products(1))
        product = db.get_next_pending()
        db.update_product_status(product["id"], "processing")
        db.update_product_status(
            product["id"], "error", error_message="API timeout"
        )
        updated = db.get_all_products()[0]
        assert updated["status"] == "error"
        assert updated["error_message"] == "API timeout"


# ── Progress ─────────────────────────────────────────────────────────


class TestGetProgress:
    def test_empty_database(self, db: Database) -> None:
        progress = db.get_progress()
        assert progress == {
            "total": 0,
            "pending": 0,
            "processing": 0,
            "done": 0,
            "error": 0,
        }

    def test_mixed_statuses(self, db: Database) -> None:
        db.insert_products(_sample_products(4))
        products = db.get_all_products()
        db.update_product_status(products[0]["id"], "processing")
        db.update_product_status(
            products[1]["id"], "done", optimized_description="ok"
        )
        db.update_product_status(
            products[2]["id"], "error", error_message="fail"
        )
        progress = db.get_progress()
        assert progress["total"] == 4
        assert progress["pending"] == 1
        assert progress["processing"] == 1
        assert progress["done"] == 1
        assert progress["error"] == 1


# ── Get all products ─────────────────────────────────────────────────


class TestGetAllProducts:
    def test_filter_by_status(self, db: Database) -> None:
        db.insert_products(_sample_products(3))
        products = db.get_all_products()
        db.update_product_status(
            products[0]["id"], "done", optimized_description="ok"
        )
        done = db.get_all_products(status="done")
        assert len(done) == 1
        assert done[0]["status"] == "done"

    def test_returns_all_when_no_filter(self, db: Database) -> None:
        db.insert_products(_sample_products(3))
        assert len(db.get_all_products()) == 3


# ── Pipeline state ───────────────────────────────────────────────────


class TestPipelineState:
    def test_default_state_is_idle(self, db: Database) -> None:
        state = db.get_pipeline_state()
        assert state["stage"] == "idle"

    def test_set_and_get_state(self, db: Database) -> None:
        db.set_pipeline_state(
            "importing", total_products=42, source_file="products.csv"
        )
        state = db.get_pipeline_state()
        assert state["stage"] == "importing"
        assert state["total_products"] == 42
        assert state["source_file"] == "products.csv"

    def test_set_state_updates_timestamp(self, db: Database) -> None:
        state_before = db.get_pipeline_state()
        db.set_pipeline_state("optimizing")
        state_after = db.get_pipeline_state()
        assert state_after["updated_at"] >= state_before["updated_at"]


# ── Column mappings ──────────────────────────────────────────────────


class TestColumnMappings:
    def test_no_mappings_initially(self, db: Database) -> None:
        assert db.get_column_mappings() == []

    def test_set_and_get_mappings(self, db: Database) -> None:
        mappings = [
            {"role": "product_id", "csv_column_name": "ProduktID", "display_name": "Product ID"},
            {
                "role": "description",
                "csv_column_name": "Beschreibung",
                "display_name": "Description",
            },
            {"role": "context", "csv_column_name": "Marke", "display_name": "Brand"},
            {"role": "context", "csv_column_name": "Titel", "display_name": "Title"},
        ]
        db.set_column_mappings(mappings)
        result = db.get_column_mappings()
        assert len(result) == 4
        assert result[0]["role"] == "product_id"
        assert result[0]["csv_column_name"] == "ProduktID"

    def test_set_replaces_previous_mappings(self, db: Database) -> None:
        db.set_column_mappings([
            {"role": "product_id", "csv_column_name": "ID"},
        ])
        db.set_column_mappings([
            {"role": "description", "csv_column_name": "Desc"},
        ])
        result = db.get_column_mappings()
        assert len(result) == 1
        assert result[0]["role"] == "description"

    def test_display_name_defaults_to_csv_column_name(self, db: Database) -> None:
        db.set_column_mappings([
            {"role": "context", "csv_column_name": "Merkmal 1"},
        ])
        result = db.get_column_mappings()
        assert result[0]["display_name"] == "Merkmal 1"


# ── Reset ────────────────────────────────────────────────────────────


class TestReset:
    def test_reset_clears_products(self, db: Database) -> None:
        db.insert_products(_sample_products(5))
        assert len(db.get_all_products()) == 5
        db.reset()
        assert len(db.get_all_products()) == 0

    def test_reset_clears_pipeline_state(self, db: Database) -> None:
        db.set_pipeline_state("optimizing", total_products=10)
        db.reset()
        state = db.get_pipeline_state()
        assert state["stage"] == "idle"
        assert state["total_products"] == 0

    def test_reset_clears_column_mappings(self, db: Database) -> None:
        db.set_column_mappings([
            {"role": "product_id", "csv_column_name": "ID"},
        ])
        db.reset()
        assert db.get_column_mappings() == []

    def test_tables_exist_after_reset(self, db: Database) -> None:
        db.reset()
        tables = {
            row[0]
            for row in db._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "products" in tables
        assert "pipeline_state" in tables
        assert "column_mappings" in tables


# ── Context manager ──────────────────────────────────────────────────


class TestContextManager:
    def test_context_manager_closes_connection(self) -> None:
        with Database(":memory:") as db:
            db.initialize()
            db.insert_products(_sample_products(1))
        # After exiting, the connection should be closed
        with pytest.raises(Exception):  # noqa: B017
            db._conn.execute("SELECT 1")
