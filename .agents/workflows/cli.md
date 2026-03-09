---
description: Build all CLI commands — daemon control, import, optimize, export, status, pause, resume, reset, logs
---

# /cli — CLI Commands

Implements the full `pdo` CLI using `click`, connecting each command to the daemon via the IPC protocol.

## Pre-requisites

- `/scaffold`, `/database`, `/core-pipeline`, and `/daemon` workflows must be completed first.

## Steps

### Client Helper

1. **Create `src/pdo/cli/client.py`** — a thin IPC client used by all CLI commands:
   - `connect(config: PdoConfig) -> socket` — connect to the daemon socket, raise `DaemonNotRunningError` if connection refused
   - `send_command(action: str, payload: dict = {}, config: PdoConfig | None = None) -> Response` — send a request and return the parsed response
   - Handles timeouts and connection errors with user-friendly messages

### Daemon Commands

2. **Create `src/pdo/cli/daemon_cmd.py`** with a `click.Group` named `daemon`:
   - `pdo daemon start` — start the daemon process (fork into background, or `--foreground` for debug)
   - `pdo daemon stop` — send `stop` command via IPC, wait for clean shutdown
   - `pdo daemon status` — check PID file + send a ping, print running/stopped status
   - Register the group on the root CLI in `main.py`

### Import Command

3. **Create `src/pdo/cli/import_cmd.py`**:
   - `pdo import <file>` — validate the file exists, send `import` action to daemon
   - Show a spinner while waiting, then print the `ImportResult` summary
   - Error if file doesn't exist or daemon is not running

### Optimize Command

4. **Create `src/pdo/cli/optimize_cmd.py`**:
   - `pdo optimize` — send `optimize` action to daemon
   - Optionally poll for status updates and display a live progress bar (using `rich`)
   - `--watch` flag to keep polling until optimization finishes

### Export Command

5. **Create `src/pdo/cli/export_cmd.py`**:
   - `pdo export <output_file>` — send `export` action to daemon
   - `--include-errors` flag to include errored products
   - Print the `ExportResult` summary

### Status & Control Commands

6. **Add commands to `src/pdo/cli/main.py`** (or a separate `control_cmd.py`):
   - `pdo status` — send `status` action, display a rich table with stage, progress N/M, percentage, ETA
   - `pdo pause` — send `pause` action, confirm paused
   - `pdo resume` — send `resume` action, confirm resumed
   - `pdo reset` — send `reset` action with confirmation prompt (`--yes` to skip prompt)

### Logs Command

7. **Create `src/pdo/cli/logs_cmd.py`**:
   - `pdo logs` — read and print the daemon log file (last N lines, default 50)
   - `--follow` / `-f` flag — tail the file and stream new lines in real-time
   - `--lines N` / `-n N` — number of lines to show
   - This command reads the log file directly (does NOT need a running daemon)

### CLI Tests

8. **Create `tests/test_cli.py`** with:
   - Use `click.testing.CliRunner` to invoke each command
   - Mock the IPC client (`send_command`) to return fixture responses
   - Test `pdo --help` renders all subcommands
   - Test `pdo daemon status` when daemon is running vs stopped
   - Test `pdo status` output formatting
   - Test `pdo import` with valid and invalid file paths
   - Test `pdo reset --yes` skips confirmation

// turbo
9. **Run all tests:**
   ```bash
   cd /Users/pdreyer/Desktop/Carta-Mondo/Scripts/product_description_optimizer
   source venv/bin/activate && python -m pytest tests/ -v
   ```

// turbo
10. **Run ruff:**
    ```bash
    source venv/bin/activate && ruff check src/pdo/cli/ tests/test_cli.py
    ```

11. **Commit:**
    ```bash
    git add -A && git commit -m "feat: implement full CLI with daemon, import, optimize, export, and control commands"
    ```
