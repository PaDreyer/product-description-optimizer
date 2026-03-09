---
description: End-to-end integration test — full pipeline from CSV import through optimization to export via the daemon
---

# /integration — End-to-End Integration Test

Verifies the complete system works end-to-end: daemon starts, CSV is imported, products are optimized, results are exported.

## Pre-requisites

- All previous workflows (`/scaffold`, `/database`, `/core-pipeline`, `/daemon`, `/cli`) must be completed.

## Steps

### Test Data

1. **Create `tests/fixtures/sample_products.csv`** with ~10 realistic product rows:
   - Columns: `product_id`, `product_name`, `category`, `description`, `price`
   - Include edge cases: empty description, long description, special characters, unicode

### Integration Test

2. **Create `tests/test_integration.py`** with a full lifecycle test:

   **Test: `test_full_pipeline`**
   - Start the daemon in foreground mode (in a thread or subprocess)
   - Send `import` command with the sample CSV
   - Assert the database contains all rows with status `pending`
   - Send `optimize` command (using `DummyOptimizer`)
   - Poll `status` until optimization completes
   - Assert all products have status `done`
   - Send `export` command to a temp file
   - Assert the exported CSV contains all rows with `optimized_description` filled
   - Send `stop` command
   - Assert the daemon has shut down cleanly

   **Test: `test_pause_resume`**
   - Start daemon, import CSV, start optimization
   - Send `pause` mid-optimization
   - Verify status shows "paused"
   - Send `resume`
   - Wait for completion
   - Verify all products are done

   **Test: `test_crash_recovery`**
   - Import CSV, start optimization
   - Kill the daemon mid-way (simulate crash)
   - Restart the daemon
   - Send `optimize` again
   - Verify only the remaining `pending` products are processed
   - Verify final counts are correct

   **Test: `test_reset`**
   - Import CSV, run optimization
   - Send `reset`
   - Verify database is empty and pipeline state is `idle`

3. **Create a `Makefile`** (or add to `pyproject.toml` scripts) with convenience commands:
   ```makefile
   .PHONY: test lint test-unit test-integration

   test-unit:
   	python -m pytest tests/ -v --ignore=tests/test_integration.py

   test-integration:
   	python -m pytest tests/test_integration.py -v

   test:
   	python -m pytest tests/ -v --cov=src/pdo --cov-report=term-missing

   lint:
   	ruff check src/ tests/
   	ruff format --check src/ tests/

   format:
   	ruff format src/ tests/
   ```

// turbo
4. **Run unit tests:**
   ```bash
   cd /Users/pdreyer/Desktop/Carta-Mondo/Scripts/product_description_optimizer
   source venv/bin/activate && make test-unit
   ```

// turbo
5. **Run integration tests:**
   ```bash
   source venv/bin/activate && make test-integration
   ```

// turbo
6. **Run full test suite with coverage:**
   ```bash
   source venv/bin/activate && make test
   ```
   Verify coverage is ≥80% on `src/pdo/core/`.

// turbo
7. **Run lint:**
   ```bash
   source venv/bin/activate && make lint
   ```

8. **Commit:**
   ```bash
   git add -A && git commit -m "test: add end-to-end integration tests and Makefile"
   ```

## Manual Smoke Test

After all automated tests pass, do a quick manual smoke test:

```bash
# Terminal 1 — Start daemon in foreground for visibility
pdo daemon start --foreground

# Terminal 2 — Run commands
pdo daemon status
pdo import tests/fixtures/sample_products.csv
pdo status
pdo optimize --watch
pdo status
pdo export /tmp/optimized_output.csv
cat /tmp/optimized_output.csv
pdo reset --yes
pdo daemon stop
```

Verify each command produces the expected output.
