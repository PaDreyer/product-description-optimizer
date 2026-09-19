"""Product description optimizer — ABC and dummy implementation.

Defines the :class:`Optimizer` protocol that any concrete backend must
implement, plus a :class:`DummyOptimizer` for development and testing.

The :func:`run_optimization` driver loops over pending products, calling
the optimizer for each one, and persists results one-by-one so that
progress survives crashes.
"""

from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pdo.core.db import Database
from pdo.core.error_groups import classify_error


class Optimizer(ABC):
    """Protocol every optimizer backend must implement."""

    @abstractmethod
    def optimize(
        self,
        product_id: str,
        description: str,
        context: dict[str, str] | None = None,
    ) -> str:
        """Return an optimized description.

        Args:
            product_id: The extracted product identifier.
            description: The original product description.
            context: Optional dict of extra context fields (title,
                feature/attribute pairs, etc.).

        Returns:
            The optimized description text.
        """


class DummyOptimizer(Optimizer):
    """Placeholder optimizer that uppercases and prefixes the description.

    Useful for development, testing, and verifying the pipeline end-to-end
    without an actual LLM integration.
    """

    def optimize(
        self,
        product_id: str,
        description: str,
        context: dict[str, str] | None = None,
    ) -> str:
        parts = [f"[OPTIMIZED] {description.upper()}"]
        if context:
            ctx_str = ", ".join(f"{k}={v}" for k, v in context.items())
            parts.append(f"Context: {ctx_str}")
        return " | ".join(parts)


@dataclass(frozen=True)
class OptimizationResult:
    """Summary returned after an optimization run."""

    total: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0


def run_optimization(
    db: Database,
    optimizer: Optimizer,
    *,
    on_progress: Callable[[int, int], Any] | None = None,
    pause_event: threading.Event | None = None,
    stop_event: threading.Event | None = None,
    product_ids: list[int] | None = None,
    request_interval: float = 0,
) -> OptimizationResult:
    """Process all ``pending`` products through the optimizer.

    Args:
        db: An initialised :class:`Database` instance.
        optimizer: An :class:`Optimizer` implementation.
        on_progress: Optional callback invoked as ``on_progress(current, total)``
            after each product is processed.
        pause_event: A :class:`threading.Event` that, when *set*, causes the
            loop to block until it is cleared.
        stop_event: A :class:`threading.Event` that, when *set*, causes the
            loop to exit early.
        product_ids: Optional batch selection; other pending rows are left untouched.
        request_interval: Interruptible delay before each product, in seconds.

    Returns:
        An :class:`OptimizationResult` summary.
    """
    db.set_pipeline_state("optimizing")

    progress = db.get_progress()
    total = progress["total"]
    succeeded = progress["done"]
    failed = progress["error"]
    current = succeeded + failed

    selected = iter(product_ids) if product_ids is not None else None

    def next_product() -> dict[str, Any] | None:
        if selected is None:
            return db.get_next_pending()
        for identifier in selected:
            item = db.get_product(identifier)
            if item and item["status"] == "pending":
                return item
        return None

    product = next_product()
    while product is not None:
        # ── Check stop ───────────────────────────────────────────
        if stop_event and stop_event.is_set():
            break

        # ── Check pause (blocking wait) ──────────────────────────
        while pause_event and pause_event.is_set():
            if stop_event and stop_event.is_set():
                break
            time.sleep(0.1)
        if stop_event and stop_event.is_set():
            break

        # ── Process one product ──────────────────────────────────
        db.update_product_status(product["id"], "processing")

        try:
            if not product.get("original_description", "").strip() and not product.get(
                "context_data"
            ):
                db.update_product_status(
                    product["id"],
                    "error",
                    error_message="Description and context fields are missing.",
                    error_kind="missing_data",
                )
                failed += 1
                current += 1
                if on_progress:
                    on_progress(current, total)
                product = next_product()
                continue
            if request_interval:
                if stop_event:
                    if stop_event.wait(request_interval):
                        db.update_product_status(product["id"], "pending")
                        break
                else:
                    time.sleep(request_interval)
            optimized = optimizer.optimize(
                product_id=product.get("product_id_value", ""),
                description=product.get("original_description", ""),
                context=product.get("context_data"),
            )
            db.update_product_status(product["id"], "done", optimized_description=optimized)
            succeeded += 1
        except Exception as exc:
            db.update_product_status(
                product["id"], "error", error_message=str(exc), error_kind=classify_error(exc)
            )
            failed += 1

        current += 1
        if on_progress:
            on_progress(current, total)

        product = next_product()

    skipped = total - succeeded - failed
    db.set_pipeline_state("idle")

    return OptimizationResult(
        total=total,
        succeeded=succeeded,
        failed=failed,
        skipped=skipped,
    )
