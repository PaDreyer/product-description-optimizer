"""SQLite database access layer for the PDO application.

Provides the :class:`Database` class that manages a single SQLite file with
tables for products, pipeline state, and column mappings.  All mutations use
parameterized queries and are wrapped in transactions.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
import threading
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from typing import Any

from pdo.core.error_groups import ERROR_GROUPS, classify_error
from pdo.exceptions import ImportDataError

_PREVIEW_TEXT_LIMIT = 250
_DETAIL_TEXT_LIMIT = 50_000
_DETAIL_METADATA_LIMIT = 5_000


def _serialized(method: Callable[..., Any]) -> Callable[..., Any]:
    """Serialize access to the shared SQLite connection."""

    @wraps(method)
    def wrapper(self: Database, *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper


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
        self._lock = threading.RLock()
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

    @_serialized
    def initialize(self) -> None:
        """Create tables if they do not already exist (idempotent)."""
        with self._conn:
            self._conn.executescript(_SCHEMA_SQL)
            columns = {row["name"] for row in self._conn.execute("PRAGMA table_info(products)")}
            if "error_kind" not in columns:
                self._conn.execute("ALTER TABLE products ADD COLUMN error_kind TEXT")
            legacy = self._conn.execute(
                "SELECT id, error_message FROM products "
                "WHERE status = 'error' AND error_kind IS NULL"
            ).fetchall()
            self._conn.executemany(
                "UPDATE products SET error_kind = ? WHERE id = ?",
                [(classify_error(row["error_message"]), row["id"]) for row in legacy],
            )

    # ── Products ─────────────────────────────────────────────────────

    @_serialized
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

    @_serialized
    def get_next_pending(self) -> dict[str, Any] | None:
        """Return the next product with status ``pending``, or *None*."""
        row = self._conn.execute(
            "SELECT * FROM products WHERE status = 'pending' ORDER BY id LIMIT 1"
        ).fetchone()
        return _row_to_dict(row) if row else None

    @_serialized
    def update_product_status(
        self,
        product_id: int,
        status: str,
        *,
        optimized_description: str | None = None,
        error_message: str | None = None,
        error_kind: str | None = None,
    ) -> None:
        """Update the status (and optionally the optimized description) of a product."""
        with self._conn:
            self._conn.execute(
                """
                UPDATE products
                   SET status = ?,
                       optimized_description = COALESCE(?, optimized_description),
                       error_message = ?,
                       error_kind = ?,
                       updated_at = CURRENT_TIMESTAMP
                 WHERE id = ?
                """,
                (
                    status,
                    optimized_description,
                    error_message,
                    (error_kind or classify_error(error_message)) if status == "error" else None,
                    product_id,
                ),
            )

    @_serialized
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

    @_serialized
    def get_all_products(self, status: str | None = None) -> list[dict[str, Any]]:
        """Fetch all products, optionally filtered by *status*."""
        if status:
            rows = self._conn.execute(
                "SELECT * FROM products WHERE status = ? ORDER BY id", (status,)
            ).fetchall()
        else:
            rows = self._conn.execute("SELECT * FROM products ORDER BY id").fetchall()
        return [_row_to_dict(r) for r in rows]

    @_serialized
    def get_product_preview(
        self, limit: int = 100, offset: int = 0, status: str | None = None, search: str = ""
    ) -> list[dict[str, Any]]:
        """Return a bounded sample of products for desktop display.

        Args:
            limit: Maximum number of rows to return.

        Returns:
            Product records ordered by import order.
        """
        where, params = self._product_filter(status, search)
        rows = self._conn.execute(
            "SELECT id, substr(product_id_value, 1, ?) AS product_id_value, "
            "substr(original_description, 1, ?) AS original_description, "
            "substr(optimized_description, 1, ?) AS optimized_description, "
            "status, substr(error_message, 1, ?) AS error_message "
            f"FROM products {where} ORDER BY id LIMIT ? OFFSET ?",
            (
                _PREVIEW_TEXT_LIMIT,
                _PREVIEW_TEXT_LIMIT,
                _PREVIEW_TEXT_LIMIT,
                _PREVIEW_TEXT_LIMIT,
                *params,
                max(0, min(limit, 100)),
                max(0, offset),
            ),
        ).fetchall()
        return [dict(row) for row in rows]

    def _product_filter(self, status: str | None, search: str) -> tuple[str, list[Any]]:
        conditions, params = [], []
        if status:
            conditions.append("status = ?")
            params.append(status)
        if search:
            conditions.append(
                "(instr(product_id_value, ?) > 0 OR instr(original_description, ?) > 0)"
            )
            params.extend([search, search])
        return ("WHERE " + " AND ".join(conditions) if conditions else ""), params

    @_serialized
    def count_products(self, status: str | None = None, search: str = "") -> int:
        """Return the count matching a paginated product query."""
        where, params = self._product_filter(status, search)
        return self._conn.execute(f"SELECT COUNT(*) FROM products {where}", params).fetchone()[0]

    @_serialized
    def get_product(self, product_id: int) -> dict[str, Any] | None:
        """Read one complete product for internal pipeline processing."""
        row = self._conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        return _row_to_dict(row) if row else None

    @_serialized
    def get_error_groups(self) -> list[dict[str, Any]]:
        """Aggregate all failed products, independent of the displayed page."""
        rows = self._conn.execute(
            "SELECT COALESCE(error_kind, 'other') AS kind, COUNT(*) AS count "
            "FROM products WHERE status = 'error' GROUP BY kind ORDER BY count DESC"
        ).fetchall()
        return [
            {
                "kind": r["kind"],
                "count": r["count"],
                "label": ERROR_GROUPS[r["kind"]][0],
                "retryable": ERROR_GROUPS[r["kind"]][1],
                "guidance": ERROR_GROUPS[r["kind"]][2],
            }
            for r in rows
        ]

    @_serialized
    def requeue_errors(self, kinds: list[str]) -> list[int]:
        """Atomically requeue selected error groups and return their internal IDs.

        Raises:
            ValueError: For unknown or non-retryable groups.
        """
        if not kinds or any(k not in ERROR_GROUPS or not ERROR_GROUPS[k][1] for k in kinds):
            raise ValueError("Select at least one retryable error group.")
        placeholders = ",".join("?" for _ in kinds)
        with self._conn:
            ids = [
                r[0]
                for r in self._conn.execute(
                    "SELECT id FROM products WHERE status = 'error' "
                    f"AND error_kind IN ({placeholders})",
                    kinds,
                )
            ]
            self._conn.execute(
                "UPDATE products SET status = 'pending', error_kind = NULL, error_message = NULL, "
                "updated_at = CURRENT_TIMESTAMP "
                f"WHERE status = 'error' AND error_kind IN ({placeholders})",
                kinds,
            )
        return ids

    @_serialized
    def apply_corrections(self, products: list[dict[str, Any]]) -> int:
        """Apply a validated correction batch by unique product ID, preserving successes.

        Raises:
            ImportDataError: If an ID is duplicate, unknown, or not an error row.
        """
        seen: set[str] = set()
        with self._conn:
            for product in products:
                key = product["product_id_value"]
                if not key or key in seen:
                    raise ImportDataError(f"Missing or duplicate product ID: {key!r}")
                seen.add(key)
                matches = self._conn.execute(
                    "SELECT id, status FROM products WHERE product_id_value = ?", (key,)
                ).fetchall()
                if len(matches) != 1 or matches[0]["status"] != "error":
                    raise ImportDataError(f"Product ID {key!r} is not uniquely in an error state.")
                if not product["original_description"].strip() and not product["context_data"]:
                    raise ImportDataError(f"Product {key!r} still has no source data.")
                self._conn.execute(
                    "UPDATE products SET raw_data = ?, original_description = ?, context_data = ?, "
                    "error_kind = 'corrected', error_message = 'Source data corrected', "
                    "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (
                        json.dumps(product["raw_data"], ensure_ascii=False),
                        product["original_description"],
                        json.dumps(product["context_data"] or {}),
                        matches[0]["id"],
                    ),
                )
        return len(products)

    @_serialized
    def set_metadata(self, key: str, value: Any) -> None:
        """Persist batch metadata as JSON."""
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                (key, json.dumps(value, ensure_ascii=False)),
            )

    @_serialized
    def get_metadata(self, key: str, default: Any = None) -> Any:
        """Read persisted batch metadata."""
        row = self._conn.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    @_serialized
    def export_page(self, scope: str, after_id: int = 0, limit: int = 500) -> list[dict[str, Any]]:
        """Read a bounded page for exports, preserving source row order."""
        filters = {
            "done": "status = 'done'",
            "all": "1 = 1",
            "completed": "status IN ('done', 'error')",
            "errors": "status = 'error'",
            "corrections": "status = 'error' AND error_kind = 'missing_data'",
        }
        if scope not in filters:
            raise ValueError("Invalid export scope.")
        rows = self._conn.execute(
            f"SELECT * FROM products WHERE id > ? AND ({filters[scope]}) ORDER BY id LIMIT ?",
            (after_id, max(0, min(limit, 500))),
        ).fetchall()
        return [_row_to_dict(row) for row in rows]

    @_serialized
    def get_product_detail(self, product_id: int) -> dict[str, Any] | None:
        """Return one product with byte-safe bounded text fields.

        Args:
            product_id: Internal database product ID.

        Returns:
            Product detail or ``None`` when the ID does not exist. Truncation
            flags indicate text that exceeded the desktop detail limit.
        """
        row = self._conn.execute(
            "SELECT id, substr(product_id_value, 1, ?) AS product_id_value, "
            "substr(original_description, 1, ?) AS original_description, "
            "substr(optimized_description, 1, ?) AS optimized_description, "
            "status, substr(error_message, 1, ?) AS error_message, "
            "length(original_description) > ? AS original_truncated, "
            "length(optimized_description) > ? AS optimized_truncated, "
            "length(error_message) > ? AS error_truncated "
            "FROM products WHERE id = ?",
            (
                _DETAIL_METADATA_LIMIT,
                _DETAIL_TEXT_LIMIT,
                _DETAIL_TEXT_LIMIT,
                _DETAIL_METADATA_LIMIT,
                _DETAIL_TEXT_LIMIT,
                _DETAIL_TEXT_LIMIT,
                _DETAIL_METADATA_LIMIT,
                product_id,
            ),
        ).fetchone()
        return dict(row) if row else None

    @_serialized
    def requeue_processing(self) -> int:
        """Return interrupted work to a consistent idle state at startup.

        Returns:
            Number of recovered product rows.
        """
        with self._conn:
            cursor = self._conn.execute(
                "UPDATE products SET status = 'pending', updated_at = CURRENT_TIMESTAMP "
                "WHERE status = 'processing'"
            )
            self._conn.execute(
                "UPDATE pipeline_state SET stage = 'idle', "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                "WHERE id = 1 AND stage IN ('importing', 'optimizing', 'exporting')"
            )
        return cursor.rowcount

    @_serialized
    def replace_from(self, source_path: Path | str) -> None:
        """Atomically replace all database contents from another SQLite file.

        This is used by the desktop importer after a CSV has been fully
        validated and imported into a staging database. The current batch is
        therefore preserved if reading or validating the new file fails.

        Args:
            source_path: Initialised SQLite database to copy from.
        """
        source = sqlite3.connect(str(source_path))
        try:
            source.backup(self._conn)
        finally:
            source.close()

    # ── Pipeline state ───────────────────────────────────────────────

    @_serialized
    def get_pipeline_state(self) -> dict[str, Any]:
        """Return the singleton pipeline-state row as a dict."""
        row = self._conn.execute("SELECT * FROM pipeline_state WHERE id = 1").fetchone()
        return dict(row) if row else {}

    @_serialized
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

    @_serialized
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

    @_serialized
    def get_column_mappings(self) -> list[dict[str, str]]:
        """Return all column mappings as a list of dicts."""
        rows = self._conn.execute(
            "SELECT role, csv_column_name, display_name FROM column_mappings ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Maintenance ──────────────────────────────────────────────────

    @_serialized
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
                           error_message = NULL,
                           error_kind = NULL;
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
                    DROP TABLE IF EXISTS metadata;
                    """
                )
        if not keep:
            self.initialize()

    @_serialized
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
CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
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
    error_kind             TEXT,
    context_data           TEXT    NOT NULL DEFAULT '{}',  -- JSON of extra context fields
    created_at             TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at             TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS products_status_id ON products(status, id);
CREATE INDEX IF NOT EXISTS products_external_id ON products(product_id_value);

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
