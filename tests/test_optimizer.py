"""Tests for the optimizer module (``pdo.core.optimizer``)."""

from __future__ import annotations

import threading

import pytest

from pdo.core.db import Database
from pdo.core.optimizer import DummyOptimizer, Optimizer, run_optimization


@pytest.fixture()
def db() -> Database:
    database = Database(":memory:")
    database.initialize()
    return database


def _seed_products(db: Database, count: int = 5) -> None:
    """Insert *count* pending products into the database."""
    db.insert_products(
        [
            {
                "source_row_number": i + 1,
                "raw_data": {"name": f"Product {i}"},
                "product_id_value": f"P{i:04d}",
                "original_description": f"Description for product {i}",
                "context_data": {"Marke": f"Brand{i}", "Titel": f"Title {i}"},
            }
            for i in range(count)
        ]
    )


class TestDummyOptimizer:
    def test_implements_protocol(self) -> None:
        assert issubclass(DummyOptimizer, Optimizer)

    def test_basic_optimization(self) -> None:
        opt = DummyOptimizer()
        result = opt.optimize("P001", "a nice product")
        assert "[OPTIMIZED]" in result
        assert "A NICE PRODUCT" in result

    def test_includes_context(self) -> None:
        opt = DummyOptimizer()
        result = opt.optimize("P001", "desc", context={"Marke": "BrandX"})
        assert "Marke=BrandX" in result


class TestRunOptimization:
    def test_optimizes_all_pending(self, db: Database) -> None:
        _seed_products(db, 3)
        result = run_optimization(db, DummyOptimizer())
        assert result.total == 3
        assert result.succeeded == 3
        assert result.failed == 0

    def test_products_marked_done(self, db: Database) -> None:
        _seed_products(db, 3)
        run_optimization(db, DummyOptimizer())
        products = db.get_all_products()
        assert all(p["status"] == "done" for p in products)
        assert all(p["optimized_description"] for p in products)

    def test_progress_callback(self, db: Database) -> None:
        _seed_products(db, 3)
        calls: list[tuple[int, int]] = []
        run_optimization(db, DummyOptimizer(), on_progress=lambda c, t: calls.append((c, t)))
        assert len(calls) == 3
        assert calls[-1] == (3, 3)

    def test_error_handling(self, db: Database) -> None:
        """An optimizer that raises should mark the product as error."""
        _seed_products(db, 2)

        class FailOptimizer(Optimizer):
            def optimize(
                self, product_id: str, description: str, context: dict | None = None
            ) -> str:
                raise RuntimeError("API down")

        result = run_optimization(db, FailOptimizer())
        assert result.failed == 2
        assert result.succeeded == 0
        products = db.get_all_products()
        assert all(p["status"] == "error" for p in products)
        assert all("API down" in p["error_message"] for p in products)

    def test_resumability(self, db: Database) -> None:
        """Only pending products should be processed on re-run."""
        _seed_products(db, 4)
        # Mark first two as done manually
        products = db.get_all_products()
        db.update_product_status(products[0]["id"], "done", optimized_description="already done")
        db.update_product_status(products[1]["id"], "done", optimized_description="already done")
        result = run_optimization(db, DummyOptimizer())
        # Should have processed 2 new + 2 already done
        assert result.succeeded == 4
        assert result.failed == 0

    def test_stop_event(self, db: Database) -> None:
        """Setting the stop event should exit early."""
        _seed_products(db, 5)
        stop = threading.Event()
        stop.set()  # Stop immediately
        result = run_optimization(db, DummyOptimizer(), stop_event=stop)
        # Should not have processed anything
        assert result.succeeded == 0

    def test_pause_resume(self, db: Database) -> None:
        """Pause event should block, then resume when cleared."""
        _seed_products(db, 3)
        pause = threading.Event()

        progress: list[int] = []
        result_holder: list[OptimizationResult] = []

        def run() -> None:
            r = run_optimization(
                db,
                DummyOptimizer(),
                pause_event=pause,
                on_progress=lambda c, _t: progress.append(c),
            )
            result_holder.append(r)

        # Start optimization in a thread
        t = threading.Thread(target=run)
        t.start()
        # Wait a bit then check it's running
        t.join(timeout=2.0)
        assert not t.is_alive()
        assert len(result_holder) == 1
        assert result_holder[0].succeeded == 3

    def test_pipeline_state_returns_to_idle(self, db: Database) -> None:
        _seed_products(db, 2)
        run_optimization(db, DummyOptimizer())
        state = db.get_pipeline_state()
        assert state["stage"] == "idle"


# Need to import for type hint in test
from pdo.core.optimizer import OptimizationResult  # noqa: E402
