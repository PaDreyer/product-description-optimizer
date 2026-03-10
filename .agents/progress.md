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
Includes extra `column_mappings` table for configurable CSV field mapping.
29 tests pass, ruff clean. Committed.

### Phase 3 — Core Pipeline (`/core-pipeline`) ✅
All three pipeline modules implemented and tested:
- `src/pdo/core/importer.py` — configurable column mappings, `;` delimiter, UTF-8/CP1252 fallback
- `src/pdo/core/optimizer.py` — ABC + DummyOptimizer, pause/stop events, per-product commits
- `src/pdo/core/exporter.py` — reconstructs CSV with optimized_description + status columns
33 new tests (62 total), ruff clean. Committed.

## Current Phase

### Phase 4 — Daemon & IPC (`/daemon`)
**Status**: Not started
**Next action**: Build `src/pdo/protocol/messages.py` following the `/daemon` workflow.

Build order:
1. IPC protocol messages (`src/pdo/protocol/messages.py`)
2. PID management (`src/pdo/daemon/pid.py`)
3. Worker engine (`src/pdo/daemon/worker.py`)
4. Socket server (`src/pdo/daemon/server.py`)
5. Tests for all

## Remaining Phases

- Phase 5 — CLI Commands (`/cli`)
- Phase 6 — Integration Tests (`/integration`)

## CSV Format Notes

- Delimiter: `;` (semicolon)
- Quoting: `"` (double-quote)
- Encoding: likely CP1252 or UTF-8 (detect at import time)
- Example header (truncated): `"PBS-Nr._";"Seite";"MWST";...;"Titel";"Beschreibung";...`
- Paired columns: `"Merkmal N"` / `"Attribut N"` (feature/attribute pairs, N=1..6)
