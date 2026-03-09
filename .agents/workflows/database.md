---
description: Build the SQLite database layer — schema, migrations, and the db.py access module
---

# /database — Database Layer

Implements the full SQLite database layer in `src/pdo/core/db.py` that all other modules depend on.

## Pre-requisites

- The `/scaffold` workflow must be completed first.

## Steps

1. **Create `src/pdo/core/db.py`** with a `Database` class:
   - `__init__(self, db_path: Path)` — opens or creates the SQLite file, enables WAL mode, sets `journal_mode` and `foreign_keys` pragmas.
   - `initialize()` — creates tables if they don't exist (idempotent).
   - `close()` — closes the connection cleanly.
   - Implement as a context manager (`__enter__` / `__exit__`).

2. **Define the schema** inside `initialize()`:

   **`products` table:**
   | Column                  | Type    | Notes                                        |
   |-------------------------|---------|----------------------------------------------|
   | `id`                    | INTEGER | Primary key, autoincrement                   |
   | `source_row_number`     | INTEGER | Original row number from CSV                 |
   | `raw_data`              | TEXT    | JSON blob of all original CSV columns        |
   | `product_name`          | TEXT    | Extracted for display/search                 |
   | `original_description`  | TEXT    | Original description from CSV                |
   | `optimized_description` | TEXT    | Result after optimization (nullable)         |
   | `status`                | TEXT    | One of: `pending`, `processing`, `done`, `error` — default `pending` |
   | `error_message`         | TEXT    | Error details if status = `error` (nullable) |
   | `created_at`            | TEXT    | ISO 8601 timestamp, default `CURRENT_TIMESTAMP` |
   | `updated_at`            | TEXT    | ISO 8601 timestamp, updated on every write   |

   **`pipeline_state` table:**
   | Column            | Type    | Notes                                          |
   |-------------------|---------|-------------------------------------------------|
   | `id`              | INTEGER | Primary key (always 1 — singleton row)          |
   | `stage`           | TEXT    | Current stage: `idle`, `importing`, `optimizing`, `exporting`, `done` |
   | `total_products`  | INTEGER | Total count after import                        |
   | `processed_count` | INTEGER | Number of products processed in current stage   |
   | `source_file`     | TEXT    | Path of the imported CSV                        |
   | `started_at`      | TEXT    | ISO 8601 timestamp                              |
   | `updated_at`      | TEXT    | ISO 8601 timestamp                              |

3. **Add data access methods** to the `Database` class:
   - `insert_products(products: list[dict]) -> int` — bulk insert, return count
   - `get_next_pending() -> dict | None` — get next product with status `pending`
   - `update_product_status(product_id: int, status: str, optimized_description: str | None, error_message: str | None)` — update a single product
   - `get_progress() -> dict` — return `{total, pending, done, error, processing}` counts
   - `get_pipeline_state() -> dict` — return current pipeline state row
   - `set_pipeline_state(stage: str, **kwargs)` — update pipeline state
   - `get_all_products(status: str | None = None) -> list[dict]` — fetch products, optionally filtered
   - `reset()` — drop all data and reinitialize tables
   - All methods must use parameterized queries and wrap mutations in transactions.

4. **Create `tests/test_db.py`** with tests for:
   - Database creation and schema initialization
   - Inserting and retrieving products
   - Status transitions (`pending` → `processing` → `done` / `error`)
   - `get_progress()` returns correct counts
   - Pipeline state management (get/set)
   - `reset()` clears everything
   - Use an **in-memory SQLite database** (`:memory:`) in fixtures

// turbo
5. **Run the tests:**
   ```bash
   cd /Users/pdreyer/Desktop/Carta-Mondo/Scripts/product_description_optimizer
   source venv/bin/activate && python -m pytest tests/test_db.py -v
   ```
   All tests must pass.

// turbo
6. **Run ruff:**
   ```bash
   source venv/bin/activate && ruff check src/pdo/core/db.py tests/test_db.py
   ```

7. **Commit:**
   ```bash
   git add -A && git commit -m "feat: implement SQLite database layer with schema and access methods"
   ```
