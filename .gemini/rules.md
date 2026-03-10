# Product Description Optimizer — Project Rules

## Project Overview

A Python CLI application that optimizes product descriptions from CSV files. The system follows a **daemon/client architecture** (inspired by `docker`, `systemctl`, `journalctl`) where a long-running background daemon performs the work and a lightweight CLI connects to it to issue commands and query status.

---

## Architecture

### Daemon/Client Model

- **Daemon (`pdod` — Product Description Optimizer Daemon)**: A background process that manages the full optimization lifecycle. It exposes a local communication interface (Unix domain socket or localhost TCP) for the CLI to connect to.
- **CLI (`pdo`)**: A thin client that connects to the running daemon to send commands and display results. It never performs optimization or database work directly.

### Communication

- Use **Unix domain sockets** (preferred) or a local **TCP socket** for IPC between CLI and daemon.
- Serialize messages using a simple JSON-based request/response protocol.
- The CLI must handle the case where the daemon is not running and report it cleanly (e.g., `Error: daemon is not running. Start it with 'pdo daemon start'`).

### Pipeline Stages

The daemon processes work through these sequential stages:

1. **Import** — Read a CSV file and load product data into a local SQLite database.
2. **Optimize** — Iterate over each product row, generate an optimized description (e.g., via LLM/API), and update the database record in-place, one product at a time.
3. **Export** — Extract the optimized data from the database back to a CSV (or other format).

Each stage must be independently resumable. Progress is tracked persistently in the database so the daemon can resume after a crash or restart.

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

pdo status                # Show current job progress (stage, product N/M, ETA)
pdo pause                 # Pause the current operation
pdo resume                # Resume a paused operation
pdo reset                 # Reset the database and all progress

pdo logs                  # Stream or tail daemon logs (like journalctl)
pdo logs --follow         # Follow log output in real-time
```

### CLI UX Principles

- Output should be human-readable by default, with a `--json` flag for machine-readable output.
- Use colored terminal output (via `rich` or `click` styling) for status, progress, and errors.
- Show progress bars or spinners where appropriate (e.g., during import or optimization).
- Exit codes must be meaningful: `0` for success, `1` for general errors, `2` for usage errors.

---

## Tech Stack & Dependencies

| Concern               | Library / Tool         | Notes                                      |
| ---------------------- | ---------------------- | ------------------------------------------ |
| CLI framework          | `click`                | Preferred for subcommand-based CLIs        |
| Terminal output        | `rich`                 | Progress bars, tables, colored output      |
| Database               | `sqlite3` (stdlib)     | No ORM — use raw SQL with parameterized queries |
| CSV parsing            | `csv` (stdlib)         | Standard library; `pandas` only if justified |
| IPC / socket comm      | `socket` (stdlib)      | Unix domain sockets for daemon/CLI comms   |
| Daemonization          | `daemon` or manual     | Use PID files for process management       |
| Async (if needed)      | `asyncio`              | Only if the daemon needs concurrent I/O    |
| Testing                | `pytest`               | With `pytest-cov` for coverage             |
| Linting                | `ruff`                 | Fast, all-in-one Python linter & formatter |
| Packaging              | `pyproject.toml`       | Modern Python packaging standard           |

---

## Database

- Use **SQLite** as the local database. One database file per optimization run.
- Store the database file inside a configurable data directory (default: `~/.pdo/data/`).
- Schema must include:
  - A `products` table with all CSV columns plus `optimized_description`, `status` (pending/processing/done/error), and timestamps.
  - A `metadata` table to track the overall pipeline state (current stage, total products, processed count, etc.).
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
│       │   └── pid.py            # PID file management
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
└── .gemini/
    └── rules.md
```

### Error Handling

- Use **custom exception classes** that inherit from a common `PdoError` base.
- Never silently swallow exceptions — always log and re-raise or handle explicitly.
- The daemon must be crash-resilient: if it dies mid-optimization, restarting should resume from the last completed product.

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
- Aim for **≥80% code coverage** on `core/` and `cli/`.
- Tests must pass before any merge or release.

---

## Configuration

- Store runtime configuration in `~/.pdo/config.toml` (or similar).
- Support environment variable overrides with a `PDO_` prefix (e.g., `PDO_DATA_DIR`).
- Configuration hierarchy (highest priority first):
  1. CLI flags / arguments
  2. Environment variables
  3. Config file (`~/.pdo/config.toml`)
  4. Built-in defaults

---

## Git & Workflow

- Commit messages follow **Conventional Commits** (`feat:`, `fix:`, `chore:`, `docs:`, etc.).
- One logical change per commit — avoid monolithic commits.
- Use feature branches and keep `main` stable.

### Commit Flow

After every completed implementation (feature, fix, refactor, etc.):

1. **Create a branch** — use a descriptive name with the appropriate prefix (`feat/`, `fix/`, `chore/`, `docs/`, etc.).
2. **Ask the user** — present the change and ask if it's ready to commit. Do **not** commit without confirmation.
3. **On approval** — stage, commit (Conventional Commits message), merge to `main` with `--no-ff`, and stay on `main`.
4. **On rejection** — apply the requested fixes first, then ask again.
