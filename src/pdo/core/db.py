"""SQLite database access layer for the PDO application.

Provides the :class:`Database` class that manages a single SQLite file with
tables for products, pipeline state, and column mappings.  All mutations use
parameterized queries and are wrapped in transactions.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
from pathlib import Path
from typing import Any


class Database:
    """Manages the local SQLite database used by the PDO pipeline.

    Usage::

        with Database(Path("products.db")) as db:
            db.initialize()
            db.insert_products([...])
    """

    def __init__(self, db_path: Path | str) -> None:
        """Open (or create) the SQLite database at *db_path*.

        Use the special string ``":memory:"`` for an in-memory database
        (useful in tests).
        """
        self._db_path = str(db_path)
        self._conn: sqlite3.Connection = sqlite3.connect(
            self._db_path,
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA foreign_keys = ON")

    # ── Context manager ──────────────────────────────────────────────

    def __enter__(self) -> Database:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        self.close()

    # ── Schema ───────────────────────────────────────────────────────

    def initialize(self) -> None:
        """Create tables if they do not already exist (idempotent)."""
        with self._conn:
            self._conn.executescript(_SCHEMA_SQL)

    # ── Products ─────────────────────────────────────────────────────

    def insert_products(self, products: list[dict[str, Any]]) -> int:
        """Bulk-insert product rows and return the number inserted.

        Each dict in *products* must contain at least::

            {
                "source_row_number": int,
                "raw_data": dict,            # original CSV row as dict
                "product_id_value": str,      # extracted product id
                "original_description": str,  # extracted description
                "context_data": dict | None,  # extra context fields
            }
        """
        sql = """
            INSERT INTO products
                (source_row_number, raw_data, product_id_value,
                 original_description, context_data)
            VALUES (?, ?, ?, ?, ?)
        """
        rows = [
            (
                p["source_row_number"],
                json.dumps(p["raw_data"], ensure_ascii=False),
                p.get("product_id_value", ""),
                p.get("original_description", ""),
                json.dumps(p.get("context_data") or {}, ensure_ascii=False),
            )
            for p in products
        ]
        with self._conn:
            self._conn.executemany(sql, rows)
        return len(rows)

    def get_next_pending(self) -> dict[str, Any] | None:
        """Return the next product with status ``pending``, or *None*."""
        row = self._conn.execute(
            "SELECT * FROM products WHERE status = 'pending' ORDER BY id LIMIT 1"
        ).fetchone()
        return _row_to_dict(row) if row else None

    def update_product_status(
        self,
        product_id: int,
        status: str,
        *,
        optimized_description: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """Update the status (and optionally the optimized description) of a product."""
        with self._conn:
            self._conn.execute(
                """
                UPDATE products
                   SET status = ?,
                       optimized_description = COALESCE(?, optimized_description),
                       error_message = COALESCE(?, error_message),
                       updated_at = CURRENT_TIMESTAMP
                 WHERE id = ?
                """,
                (status, optimized_description, error_message, product_id),
            )

    def get_progress(self) -> dict[str, int]:
        """Return counts of products by status.

        Returns::

            {"total": int, "pending": int, "processing": int, "done": int, "error": int}
        """
        rows = self._conn.execute(
            "SELECT status, COUNT(*) AS cnt FROM products GROUP BY status"
        ).fetchall()
        counts: dict[str, int] = {
            "total": 0,
            "pending": 0,
            "processing": 0,
            "done": 0,
            "error": 0,
        }
        for row in rows:
            counts[row["status"]] = row["cnt"]
            counts["total"] += row["cnt"]
        return counts

    def get_all_products(self, status: str | None = None) -> list[dict[str, Any]]:
        """Fetch all products, optionally filtered by *status*."""
        if status:
            rows = self._conn.execute(
                "SELECT * FROM products WHERE status = ? ORDER BY id", (status,)
            ).fetchall()
        else:
            rows = self._conn.execute("SELECT * FROM products ORDER BY id").fetchall()
        return [_row_to_dict(r) for r in rows]

    # ── Pipeline state ───────────────────────────────────────────────

    def get_pipeline_state(self) -> dict[str, Any]:
        """Return the singleton pipeline-state row as a dict."""
        row = self._conn.execute("SELECT * FROM pipeline_state WHERE id = 1").fetchone()
        return dict(row) if row else {}

    def set_pipeline_state(self, stage: str, **kwargs: Any) -> None:
        """Update the pipeline state.  Extra keyword arguments are set as columns.

        Example::

            db.set_pipeline_state("importing", total_products=42, source_file="in.csv")
        """
        allowed = {"total_products", "processed_count", "source_file"}
        extra_cols = {k: v for k, v in kwargs.items() if k in allowed}

        sets = ["stage = ?", "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"]
        params: list[Any] = [stage]
        for col, val in extra_cols.items():
            sets.append(f"{col} = ?")
            params.append(val)

        sql = f"UPDATE pipeline_state SET {', '.join(sets)} WHERE id = 1"
        with self._conn:
            self._conn.execute(sql, params)

    # ── Column mappings ──────────────────────────────────────────────

    def set_column_mappings(self, mappings: list[dict[str, str]]) -> None:
        """Replace all column mappings with the given list.

        Each dict must have ``role``, ``csv_column_name``, and optionally
        ``display_name``.
        """
        with self._conn:
            self._conn.execute("DELETE FROM column_mappings")
            self._conn.executemany(
                """
                INSERT INTO column_mappings (role, csv_column_name, display_name)
                VALUES (?, ?, ?)
                """,
                [
                    (m["role"], m["csv_column_name"], m.get("display_name", m["csv_column_name"]))
                    for m in mappings
                ],
            )

    def get_column_mappings(self) -> list[dict[str, str]]:
        """Return all column mappings as a list of dicts."""
        rows = self._conn.execute(
            "SELECT role, csv_column_name, display_name FROM column_mappings ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Maintenance ──────────────────────────────────────────────────

    def reset(self, keep: bool = False) -> None:
        """Drop all data and reinitialize the schema.
        
        If keep is True, retain products and mappings but flag all products as pending
        and reset pipeline state metrics.
        """
        with self._conn:
            if keep:
                self._conn.executescript(
                    """
                    UPDATE products 
                       SET status = 'pending', 
                           optimized_description = NULL, 
                           error_message = NULL;
                    UPDATE pipeline_state 
                       SET stage = 'idle', 
                           processed_count = 0;
                    """
                )
            else:
                self._conn.executescript(
                    """
                    DROP TABLE IF EXISTS column_mappings;
                    DROP TABLE IF EXISTS products;
                    DROP TABLE IF EXISTS pipeline_state;
                    """
                )
        if not keep:
            self.initialize()

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()


# ── Private helpers ──────────────────────────────────────────────────


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Convert a sqlite3.Row to a plain dict, deserializing JSON columns."""
    d = dict(row)
    for json_col in ("raw_data", "context_data"):
        if json_col in d and isinstance(d[json_col], str):
            with contextlib.suppress(json.JSONDecodeError, TypeError):
                d[json_col] = json.loads(d[json_col])
    return d


# ── SQL ──────────────────────────────────────────────────────────────

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS products (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    source_row_number      INTEGER NOT NULL,
    raw_data               TEXT    NOT NULL,  -- JSON blob of all original CSV columns
    product_id_value       TEXT    NOT NULL DEFAULT '',
    original_description   TEXT    NOT NULL DEFAULT '',
    optimized_description  TEXT,
    status                 TEXT    NOT NULL DEFAULT 'pending'
                           CHECK (status IN ('pending', 'processing', 'done', 'error')),
    error_message          TEXT,
    context_data           TEXT    NOT NULL DEFAULT '{}',  -- JSON of extra context fields
    created_at             TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at             TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS pipeline_state (
    id               INTEGER PRIMARY KEY CHECK (id = 1),  -- singleton row
    stage            TEXT    NOT NULL DEFAULT 'idle'
                     CHECK (stage IN ('idle', 'importing', 'optimizing', 'exporting', 'done')),
    total_products   INTEGER NOT NULL DEFAULT 0,
    processed_count  INTEGER NOT NULL DEFAULT 0,
    source_file      TEXT,
    started_at       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Seed the singleton pipeline_state row if it doesn't exist.
INSERT OR IGNORE INTO pipeline_state (id) VALUES (1);

CREATE TABLE IF NOT EXISTS column_mappings (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    role             TEXT NOT NULL,  -- e.g. 'product_id', 'description', 'context'
    csv_column_name  TEXT NOT NULL,  -- header name from the CSV
    display_name     TEXT NOT NULL   -- human-readable label
);
"""
