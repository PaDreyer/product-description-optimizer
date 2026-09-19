# Product Description Optimizer — Project Rules

## Project Overview

A desktop and CLI application that optimizes product descriptions from CSV files. A long-running daemon performs the work while both interfaces act as clients.

---

## Architecture

### Daemon/Client Model

- **Daemon**: A background process that manages the full optimization lifecycle. The CLI and GUI start it through the same detached subprocess launcher.
- **CLI (`pdo`) and desktop (`pdo-desktop`)**: Clients that connect to the running daemon to send commands and display results. They do not perform optimization or database work directly.

### Communication

- Use an authenticated loopback **TCP socket** for IPC on Linux and Windows. The endpoint file in the data directory publishes the port and token with owner-only permissions.
- Serialize messages using a simple JSON-based request/response protocol.
- The CLI must handle the case where the daemon is not running and report it cleanly (e.g., `Error: daemon is not running. Start it with 'pdo daemon start'`).

### Pipeline Stages

The daemon processes work through these sequential stages:

1. **Import** — Read a CSV file and load product data into a local SQLite database.
2. **Optimize** — Iterate over each product row, generate an optimized description (e.g., via LLM/API), and update the database record in-place, one product at a time.
3. **Export** — Extract the optimized data from the database back to a CSV (or other format).

Optimization progress is persisted per product. On daemon startup, interrupted `processing` rows return to `pending`; the user must start optimization again. `resume` only unpauses an existing job. Interrupted imports and exports must be restarted. Desktop replacement import stages the new batch before replacing the current one; CLI import appends rows. See [Development guide](../../docs/development.md) for current behavior.

---

## CLI Design

### Command Structure

Follow a **noun-verb** or **verb-noun** pattern similar to `docker` / `systemctl`:

```
pdo daemon start          # Start the background daemon
pdo daemon stop           # Gracefully stop the daemon
pdo daemon status         # Show whether the daemon is running

pdo import <file.csv>     # Queue a CSV file for import
pdo optimize              # Start/resume the optimization run
pdo export <file.csv>     # Export optimized data to CSV

pdo status                # Show stage, product counts, percentage, and pause state
pdo pause                 # Pause the current operation
pdo resume                # Unpause an existing optimization job
pdo reset                 # Reset the database and all progress

pdo logs                  # Stream or tail daemon logs (like journalctl)
pdo logs --follow         # Follow log output in real-time
```

### CLI UX Principles

- Output should be human-readable by default, with a `--json` flag for machine-readable output.
- Use colored terminal output (via `rich` or `click` styling) for status, progress, and errors.
- Show progress bars or spinners where appropriate (e.g., during import or optimization).
- Exit-code target: `0` for success, `1` for general errors, `2` for usage errors. Current commands do not consistently return nonzero on daemon errors; automation must also inspect JSON and background-job results. See the [CLI Reference](../../docs/cli_reference.md).

---

## Tech Stack & Dependencies

| Concern               | Library / Tool         | Notes                                      |
| ---------------------- | ---------------------- | ------------------------------------------ |
| CLI framework          | `click`                | Preferred for subcommand-based CLIs        |
| Terminal output        | `rich`                 | Progress bars, tables, colored output      |
| Database               | `sqlite3` (stdlib)     | No ORM — use raw SQL with parameterized queries |
| CSV parsing            | `csv` (stdlib)         | Standard library; `pandas` only if justified |
| IPC / socket comm      | `socket` (stdlib)      | Authenticated loopback TCP                 |
| Daemon launch          | `subprocess` (stdlib)  | Shared GUI/CLI launcher with readiness notification |
| Async (if needed)      | `asyncio`              | Only if the daemon needs concurrent I/O    |
| Testing                | `pytest`               | With `pytest-cov` for coverage             |
| Linting                | `ruff`                 | Fast, all-in-one Python linter & formatter |
| Desktop GUI            | `PySide6`, `dbus-next` | Qt screens; Linux StatusNotifierItem tray   |
| Packaging              | `pyproject.toml`, PyInstaller | AppImage, Debian package, Windows Inno Setup installer |

---

## Database

- Use **SQLite** as the local database. One active batch in `pdo.db` per data directory; successive runs share it.
- Store the database file inside a configurable data directory (default: `~/.pdo/data/`).
- Schema must include:
  - A `products` table with original CSV columns stored in `raw_data` JSON, extracted ID/description/context, optimized text, status (`pending`/`processing`/`done`/`error`), error category/message, and timestamps.
  - A singleton `pipeline_state` table for stage, source path, and counters.
  - `column_mappings` for semantic roles and `metadata` for source headers/CSV format.
- All database access must use **parameterized queries** — never interpolate user data into SQL strings.
- Wrap multi-step mutations in **transactions**.

---

## Code Style & Conventions

### General

- **Python 3.12+** — use modern syntax (type hints, `match` statements, f-strings, `|` union types).
- **Type hints everywhere** — all function signatures, return types, and non-trivial variables.
- **Docstrings** — use Google-style docstrings on all public functions, classes, and modules.
- **No global mutable state** — pass dependencies explicitly (database connections, config objects).
- **Keep functions small** — each function should do one thing. If a function exceeds ~30 lines, consider refactoring.

### Naming

- `snake_case` for functions, variables, modules, and file names.
- `PascalCase` for classes.
- `UPPER_SNAKE_CASE` for constants.
- Prefix private/internal helpers with `_`.

### Project Structure

```
product_description_optimizer/
├── pyproject.toml
├── README.md
├── src/
│   └── pdo/
│       ├── __init__.py
│       ├── cli/                  # CLI entry points and command groups
│       │   ├── __init__.py
│       │   ├── main.py           # Root CLI group
│       │   ├── daemon_cmd.py     # `pdo daemon` subcommands
│       │   ├── import_cmd.py     # `pdo import` command
│       │   ├── optimize_cmd.py   # `pdo optimize` command
│       │   └── export_cmd.py     # `pdo export` command
│       ├── daemon/               # Daemon process logic
│       │   ├── __init__.py
│       │   ├── server.py         # Socket server & request dispatcher
│       │   ├── worker.py         # Pipeline execution engine
│       │   ├── pid.py            # PID file management
│       │   ├── endpoint.py       # Authenticated endpoint discovery
│       │   ├── entry.py          # Detached process entry point
│       │   ├── launcher.py       # Shared CLI/GUI startup
│       │   ├── lifecycle.py      # Shutdown and runtime cleanup
│       │   └── startup.py        # Readiness notification
│       ├── desktop/              # PySide6 GUI and Linux tray
│       ├── core/                 # Shared business logic
│       │   ├── __init__.py
│       │   ├── db.py             # Database access layer
│       │   ├── importer.py       # CSV → SQLite import logic
│       │   ├── optimizer.py      # Description optimization logic
│       │   └── exporter.py       # SQLite → CSV export logic
│       ├── protocol/             # IPC message definitions
│       │   ├── __init__.py
│       │   └── messages.py       # Request/response dataclasses
│       └── config.py             # Configuration & paths
├── tests/
│   ├── conftest.py
│   ├── test_db.py
│   ├── test_importer.py
│   ├── test_optimizer.py
│   └── test_exporter.py
└── AGENTS.md                    # Current development instructions
```

### Error Handling

- Use **custom exception classes** that inherit from a common `PdoError` base.
- Never silently swallow exceptions — always log and re-raise or handle explicitly.
- Preserve completed products after a crash. Startup requeues interrupted products, and a new optimization request processes pending rows. Failed products require an explicit retry.

### Logging

- Use Python's `logging` module with structured output.
- The daemon writes logs to `~/.pdo/logs/daemon.log` with rotation.
- Log levels: `DEBUG` for development, `INFO` for normal operation, `WARNING`/`ERROR` for issues.
- The `pdo logs` command reads and streams the daemon log file.

---

## Testing

- All business logic in `core/` must have unit tests.
- Use **fixtures** for database setup/teardown (in-memory SQLite for tests).
- Test the CLI commands using `click.testing.CliRunner`.
- Aim for **≥80% code coverage** on `src/pdo/`; use `make test` to inspect it. CI currently runs tests without a numeric coverage gate.
- Tests must pass before any merge or release.

---

## Configuration

- Store runtime configuration in `~/.pdo/config.toml` (or similar).
- Support environment variable overrides with a `PDO_` prefix (e.g., `PDO_DATA_DIR`).
- Configuration hierarchy (highest priority first):
  1. Explicit overrides passed to `load_config`
  2. `PDO_` environment variables
  3. Config file (`~/.pdo/config.toml`)
  4. Built-in defaults
- Command options must explicitly forward their config/overrides. The CLI currently honors `--config` only for config management and optimizer listing. Provider API-key environment variables are fallbacks behind nonempty saved keys. See [Configuration reference](../../docs/cli_reference.md#configuration-reference) for refresh behavior and limitations.

---

## Git & Workflow

- Commit messages follow **Conventional Commits** (`feat:`, `fix:`, `chore:`, `docs:`, etc.).
- One logical change per commit — avoid monolithic commits.
- Work on the current branch. Create or switch branches only when the user explicitly requests it.

### Commit Flow

After every completed implementation (feature, fix, refactor, etc.):

1. **Ask the user** — present the change and ask if it's ready to commit. Do **not** commit without confirmation.
2. **On approval** — stage and commit (Conventional Commits message) on the current branch. Merge only when the user explicitly requests it.
3. **On rejection** — apply the requested fixes first, then ask again.
