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

### Phase 5 — CLI Commands (`/cli`) ✅
- `cli/client.py` — IPC client helper (connect, send_command)
- `cli/daemon_cmd.py` — start/stop/status
- `cli/import_cmd.py` — `pdo import <file> -m ROLE:COLUMN`
- `cli/optimize_cmd.py` — `pdo optimize [--watch]`
- `cli/export_cmd.py` — `pdo export <output_file> [--include-errors]`
- `cli/logs_cmd.py` — `pdo logs [-f] [-n N]`
- `main.py` updated — status/pause/resume/reset commands, all subcommands registered
20 new tests (109 total).

## Current Phase

### Phase 6 — Integration Tests (`/integration`)
**Status**: Not started
**Next action**: Build an end-to-end test (`tests/test_integration.py`) that exercises
the full pipeline: CSV import → optimize → export via the daemon, verifying the output CSV.

## CSV Format Notes

- Delimiter: `;` (semicolon)
- Quoting: `"` (double-quote)
- Encoding: likely CP1252 or UTF-8 (detect at import time)
- Paired columns: `"Merkmal N"` / `"Attribut N"` (feature/attribute pairs, N=1..6)
