---
description: Build the daemon — IPC protocol, socket server, worker engine, PID management
---

# /daemon — Daemon & IPC Layer

Implements the background daemon process that the CLI communicates with via Unix domain sockets.

## Pre-requisites

- `/scaffold`, `/database`, and `/core-pipeline` workflows must be completed first.

## Steps

### IPC Protocol

1. **Create `src/pdo/protocol/messages.py`** with request/response dataclasses:

   ```
   # Requests (CLI → Daemon)
   Request(action: str, payload: dict)

   # Supported actions:
   # - "import"    → payload: {"csv_path": str}
   # - "optimize"  → payload: {}
   # - "export"    → payload: {"output_path": str}
   # - "status"    → payload: {}
   # - "pause"     → payload: {}
   # - "resume"    → payload: {}
   # - "reset"     → payload: {}
   # - "stop"      → payload: {}
   # - "logs"      → payload: {"follow": bool, "lines": int}

   # Response (Daemon → CLI)
   Response(success: bool, data: dict, error: str | None)
   ```

   - Add `to_json() -> str` and `from_json(raw: str) -> Self` classmethods for serialization
   - Messages are newline-delimited JSON over the socket
   - Add a `send_message(sock, msg)` and `receive_message(sock) -> dict` helper that handles framing (length-prefix or newline-delimited)

### PID Management

2. **Create `src/pdo/daemon/pid.py`** with:
   - `write_pid(pid_path: Path)` — write current PID to file
   - `read_pid(pid_path: Path) -> int | None` — read PID, return None if missing/stale
   - `is_daemon_running(pid_path: Path) -> bool` — check if PID file exists AND process is alive (use `os.kill(pid, 0)`)
   - `remove_pid(pid_path: Path)` — clean up PID file
   - PID file default location: `~/.pdo/daemon.pid`

### Worker Engine

3. **Create `src/pdo/daemon/worker.py`** with a `Worker` class:
   - Runs pipeline stages in a background thread
   - Holds a `threading.Event` for pause/resume control
   - Holds a `threading.Event` for stop/shutdown signaling
   - Public methods:
     - `start_import(csv_path: Path)` — runs importer in a worker thread
     - `start_optimization()` — runs optimizer in a worker thread
     - `start_export(output_path: Path)` — runs exporter in a worker thread
     - `pause()` — signals the pause event
     - `resume()` — clears the pause event
     - `stop()` — signals the stop event and waits for the worker thread to finish
     - `get_status() -> dict` — returns current activity status, progress, stage info
   - Only one operation runs at a time — reject commands if busy

### Socket Server

4. **Create `src/pdo/daemon/server.py`** with a `DaemonServer` class:
   - Binds to a Unix domain socket (path from config)
   - `start()` — main loop: accept connections, read request, dispatch to worker, send response
   - `shutdown()` — close the socket, clean up PID file
   - Use `selectors` or `asyncio` for non-blocking I/O so the server can handle commands while a worker thread runs
   - Register signal handlers: `SIGTERM` / `SIGINT` → graceful shutdown
   - On startup: check if another daemon is already running (PID check) — refuse to start if so
   - Handle `daemonize()` to fork into the background (or offer a `--foreground` flag for debugging)
   - Request dispatcher maps `action` strings to worker methods using a clean dispatch table (dict or match statement)

### Integration

5. **Create `tests/test_protocol.py`** with:
   - Test serialization/deserialization round-trips for all message types
   - Test malformed JSON handling

6. **Create `tests/test_daemon.py`** with:
   - Test PID file creation, reading, and staleness detection
   - Test worker start/pause/resume/stop lifecycle
   - Test that the server accepts a connection and responds (use a local socket in `tmp_path`)
   - Test concurrent command while worker is running

// turbo
7. **Run all tests:**
   ```bash
   cd /Users/pdreyer/Desktop/Carta-Mondo/Scripts/product_description_optimizer
   source venv/bin/activate && python -m pytest tests/ -v
   ```

// turbo
8. **Run ruff:**
   ```bash
   source venv/bin/activate && ruff check src/pdo/daemon/ src/pdo/protocol/ tests/
   ```

9. **Commit:**
   ```bash
   git add -A && git commit -m "feat: implement daemon server, worker engine, and IPC protocol"
   ```
