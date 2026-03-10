# Project Progress Tracker

This file tracks the current build progress so any new agent context knows exactly
where to pick up.  Check the workflows in `.agents/workflows/` for detailed step
instructions for each phase.

## Completed Phases

### Phase 1 — Scaffold (`/scaffold`) ✅
All steps done: project structure, `pyproject.toml`, `config.py`, `exceptions.py`,
`cli/main.py`, `tests/conftest.py`, editable install verified.

### Phase 2 — Database Layer (`/database`) ✅
`src/pdo/core/db.py` and `tests/test_db.py` — 29 tests.
Includes `column_mappings` table for configurable CSV field mapping.

### Phase 3 — Core Pipeline (`/core-pipeline`) ✅
- `importer.py` — configurable column mappings, `;` delimiter, UTF-8/CP1252 fallback
- `optimizer.py` — ABC + DummyOptimizer, pause/stop events, per-product commits
- `exporter.py` — reconstructs CSV with optimized_description + status columns
33 new tests (62 total).

### Phase 4 — Daemon & IPC (`/daemon`) ✅
- `protocol/messages.py` — Request/Response dataclasses, JSON framing, socket helpers
- `daemon/pid.py` — PID file write/read/stale detection/signal
- `daemon/worker.py` — threaded pipeline operations, pause/stop, busy rejection
- `daemon/server.py` — Unix domain socket server, selectors I/O, dispatch table, daemonize
27 new tests (89 total).

## Current Phase

### Phase 5 — CLI Commands (`/cli`)
**Status**: Not started
**Next action**: Build `src/pdo/cli/client.py` following the `/cli` workflow.

Build order:
1. IPC client helper (`src/pdo/cli/client.py`)
2. Daemon commands (`src/pdo/cli/daemon_cmd.py`)
3. Import command (`src/pdo/cli/import_cmd.py`)
4. Optimize command (`src/pdo/cli/optimize_cmd.py`)
5. Export command (`src/pdo/cli/export_cmd.py`)
6. Status/control commands (in `main.py` or `control_cmd.py`)
7. Logs command (`src/pdo/cli/logs_cmd.py`)
8. Tests (`tests/test_cli.py`)

## Remaining Phases

- Phase 6 — Integration Tests (`/integration`)

## CSV Format Notes

- Delimiter: `;` (semicolon)
- Quoting: `"` (double-quote)
- Encoding: likely CP1252 or UTF-8 (detect at import time)
- Paired columns: `"Merkmal N"` / `"Attribut N"` (feature/attribute pairs, N=1..6)
