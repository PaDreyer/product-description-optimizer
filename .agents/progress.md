# Project Progress Tracker

This file tracks the current build progress so any new agent context knows exactly
where to pick up.  Check the workflows in `.agents/workflows/` for detailed step
instructions for each phase.

## Completed Phases

### Phase 1 — Scaffold (`/scaffold`) ✅
All steps done: project structure, `pyproject.toml`, `config.py`, `exceptions.py`,
`cli/main.py`, `tests/conftest.py`, editable install verified.

### Phase 2 — Database Layer (`/database`) ✅
`src/pdo/core/db.py` and `tests/test_db.py` implemented.
Includes extra `column_mappings` table for configurable CSV field mapping
(user specifies which CSV columns map to product_id, description, and context fields).
29 tests pass, ruff clean. **Pending git commit.**

## Current Phase

### Phase 3 — Core Pipeline (`/core-pipeline`)
**Status**: Not started
**Next action**: Build `src/pdo/core/importer.py` following `/core-pipeline` workflow.

Key design note for the **importer**: The CSV uses `;` as delimiter and has many
columns (60+). Users must specify column mappings at import time:
- `--id-col` for the product ID column (e.g. `"ProduktID"`)
- `--description-col` for the description column (e.g. `"Beschreibung"`)
- `--context-cols` for additional context columns to feed the optimizer
  (e.g. `"Marke,Titel,Merkmal 1,Attribut 1,Merkmal 2,Attribut 2,..."`)

The mappings are stored in the `column_mappings` table in the database.

## Remaining Phases

- Phase 4 — Daemon & IPC (`/daemon`)
- Phase 5 — CLI Commands (`/cli`)
- Phase 6 — Integration Tests (`/integration`)

## CSV Format Notes

- Delimiter: `;` (semicolon)
- Quoting: `"` (double-quote)
- Encoding: likely CP1252 or UTF-8 (detect at import time)
- Example header (truncated): `"PBS-Nr._";"Seite";"MWST";...;"Titel";"Beschreibung";...`
- Paired columns: `"Merkmal N"` / `"Attribut N"` (feature/attribute pairs, N=1..6)
