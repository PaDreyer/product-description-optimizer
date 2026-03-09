---
description: Build the three core pipeline modules — importer, optimizer, and exporter
---

# /core-pipeline — Core Business Logic

Implements the three pipeline stages as independent, testable modules in `src/pdo/core/`.

## Pre-requisites

- `/scaffold` and `/database` workflows must be completed first.

## Steps

### Importer

1. **Create `src/pdo/core/importer.py`** with:
   - `import_csv(db: Database, csv_path: Path) -> ImportResult` function
   - Read the CSV using `csv.DictReader`
   - Validate that the CSV is non-empty and has expected columns (at minimum: a name and description column — exact column names should be configurable or auto-detected)
   - Insert rows into the `products` table via `db.insert_products()`
   - Update the pipeline state to `importing`, then `idle` when done
   - Return an `ImportResult` dataclass with: `total_rows`, `imported_count`, `skipped_count`, `errors`
   - Handle edge cases: empty file, duplicate imports (warn or skip), malformed rows

2. **Create `tests/test_importer.py`** with:
   - Test importing a valid CSV (use `tmp_path` to create a test CSV file)
   - Test with missing description column
   - Test with empty CSV
   - Test with CSV containing special characters / unicode
   - Verify database state after import (row counts, statuses)

### Optimizer

3. **Create `src/pdo/core/optimizer.py`** with:
   - An `Optimizer` protocol/ABC defining: `optimize(product_name: str, description: str) -> str`
   - A `DummyOptimizer` implementation that returns a simple transformed description (for development/testing — e.g., uppercases the text or adds a prefix). This is a **placeholder** until a real LLM integration is added.
   - A `run_optimization(db: Database, optimizer: Optimizer, on_progress: Callable | None = None) -> OptimizationResult` function that:
     - Sets pipeline state to `optimizing`
     - Loops: `db.get_next_pending()` → sets status to `processing` → calls `optimizer.optimize()` → updates the product with result → sets status to `done` (or `error` on failure)
     - Calls `on_progress(current, total)` after each product if provided
     - Supports **pausing**: check a `threading.Event` or similar flag before each iteration
     - Returns `OptimizationResult` dataclass with: `total`, `succeeded`, `failed`, `skipped`
   - Each product is committed individually so progress survives crashes

4. **Create `tests/test_optimizer.py`** with:
   - Test optimization of a single product
   - Test full batch optimization with multiple products
   - Test error handling (optimizer raises exception → product marked as `error`, pipeline continues)
   - Test pause/resume mechanism
   - Test resumability: insert some products as `done`, verify only `pending` ones are processed

### Exporter

5. **Create `src/pdo/core/exporter.py`** with:
   - `export_csv(db: Database, output_path: Path, include_errors: bool = False) -> ExportResult` function
   - Fetch all products with status `done` (and optionally `error`)
   - Write to CSV: original columns + `optimized_description` + `status`
   - Reconstruct the original CSV columns from the `raw_data` JSON blob
   - Update pipeline state to `exporting`, then `done` when complete
   - Return `ExportResult` dataclass with: `total_exported`, `output_path`

6. **Create `tests/test_exporter.py`** with:
   - Test exporting after a complete optimization run
   - Test that exported CSV contains original + optimized columns
   - Test `include_errors` flag
   - Test export to a real file (verify file is readable)

// turbo
7. **Run all tests:**
   ```bash
   cd /Users/pdreyer/Desktop/Carta-Mondo/Scripts/product_description_optimizer
   source venv/bin/activate && python -m pytest tests/ -v
   ```
   All tests must pass.

// turbo
8. **Run ruff on all core modules:**
   ```bash
   source venv/bin/activate && ruff check src/pdo/core/ tests/
   ```

9. **Commit:**
   ```bash
   git add -A && git commit -m "feat: implement importer, optimizer, and exporter pipeline modules"
   ```
