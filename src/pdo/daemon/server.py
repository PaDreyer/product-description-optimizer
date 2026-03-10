"""Daemon socket server — accepts CLI commands over a Unix domain socket.

The server binds to the configured socket path, dispatches incoming
:class:`Request` messages to the :class:`Worker`, and sends back
:class:`Response` messages.
"""

from __future__ import annotations

import logging
import os
import selectors
import signal
import socket
import sys
from pathlib import Path
from typing import Any

from pdo.config import PdoConfig, load_config
from pdo.core.db import Database
from pdo.daemon.pid import is_daemon_running, remove_pid, write_pid
from pdo.daemon.worker import Worker
from pdo.protocol.messages import (
    Request,
    Response,
    receive_message,
    send_message,
)

log = logging.getLogger(__name__)


class DaemonServer:
    """Unix domain socket server for the PDO daemon."""

    def __init__(self, config: PdoConfig | None = None) -> None:
        self._config = config or load_config()
        self._socket_path = self._config.socket_path
        self._pid_path = self._config.data_dir / "daemon.pid"
        self._db: Database | None = None
        self._worker: Worker | None = None
        self._running = False
        self._server_sock: socket.socket | None = None
        self._sel: selectors.DefaultSelector | None = None

    # ── Lifecycle ────────────────────────────────────────────────────

    def start(self, *, foreground: bool = False) -> None:
        """Start the daemon.

        Args:
            foreground: If *True*, run in the current process (for debugging).
                Otherwise fork into the background.
        """
        if is_daemon_running(self._pid_path):
            log.error("Daemon is already running")
            sys.exit(1)

        if not foreground:
            _daemonize()

        self._setup()
        log.info("Daemon started (pid=%d, socket=%s)", os.getpid(), self._socket_path)

        try:
            self._serve()
        except KeyboardInterrupt:
            log.info("Received keyboard interrupt")
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        """Gracefully shut down the daemon."""
        self._running = False
        log.info("Shutting down daemon …")

        if self._worker:
            self._worker.stop()

        if self._sel:
            self._sel.close()

        if self._server_sock:
            self._server_sock.close()

        # Remove socket file
        self._socket_path.unlink(missing_ok=True)
        remove_pid(self._pid_path)

        if self._db:
            self._db.close()

        log.info("Daemon stopped")

    # ── Internal setup ───────────────────────────────────────────────

    def _setup(self) -> None:
        """Initialise database, worker, socket, and signal handlers."""
        # Ensure directories exist
        self._config.data_dir.mkdir(parents=True, exist_ok=True)
        self._config.log_dir.mkdir(parents=True, exist_ok=True)

        # Write PID
        write_pid(self._pid_path)

        # Database
        db_path = self._config.data_dir / "pdo.db"
        self._db = Database(db_path)
        self._db.initialize()

        # Worker
        self._worker = Worker(self._db)

        # Socket
        self._socket_path.unlink(missing_ok=True)
        self._server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.bind(str(self._socket_path))
        self._server_sock.listen(5)
        self._server_sock.setblocking(False)

        # Selector for non-blocking I/O
        self._sel = selectors.DefaultSelector()
        self._sel.register(self._server_sock, selectors.EVENT_READ)

        # Signal handlers
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

        self._running = True

    def _serve(self) -> None:
        """Main accept loop."""
        assert self._sel is not None
        while self._running:
            events = self._sel.select(timeout=1.0)
            for key, _ in events:
                if key.fileobj is self._server_sock:
                    self._accept_connection()

    def _accept_connection(self) -> None:
        """Accept a single client connection and handle the request."""
        assert self._server_sock is not None
        conn, _ = self._server_sock.accept()
        try:
            conn.settimeout(5.0)
            raw = receive_message(conn)
            request = Request(**raw)
            response = self._dispatch(request)
            send_message(conn, response)
        except Exception:
            log.exception("Error handling client connection")
            try:
                send_message(conn, Response(success=False, error="Internal server error"))
            except Exception:
                log.exception("Failed to send error response")
        finally:
            conn.close()

    # ── Dispatch ─────────────────────────────────────────────────────

    def _dispatch(self, request: Request) -> Response:
        """Route a request to the appropriate handler."""
        assert self._worker is not None

        handlers: dict[str, Any] = {
            "import": self._handle_import,
            "optimize": self._handle_optimize,
            "export": self._handle_export,
            "status": self._handle_status,
            "pause": self._handle_pause,
            "resume": self._handle_resume,
            "reset": self._handle_reset,
            "stop": self._handle_stop,
            "ping": self._handle_ping,
        }

        handler = handlers.get(request.action)
        if handler is None:
            return Response(success=False, error=f"Unknown action: {request.action}")

        try:
            return handler(request.payload)
        except Exception as exc:
            log.exception("Handler error for action '%s'", request.action)
            return Response(success=False, error=str(exc))

    # ── Handlers ─────────────────────────────────────────────────────

    def _handle_import(self, payload: dict[str, Any]) -> Response:
        assert self._worker is not None
        csv_path = payload.get("csv_path")
        if not csv_path:
            return Response(success=False, error="Missing 'csv_path' in payload")
        column_mappings = payload.get("column_mappings", [])
        delimiter = payload.get("delimiter", ";")
        started = self._worker.start_import(
            Path(csv_path), column_mappings, delimiter=delimiter
        )
        if not started:
            return Response(success=False, error="Worker is busy")
        return Response(success=True, data={"message": "Import started"})

    def _handle_optimize(self, payload: dict[str, Any]) -> Response:
        assert self._worker is not None
        started = self._worker.start_optimization()
        if not started:
            return Response(success=False, error="Worker is busy")
        return Response(success=True, data={"message": "Optimization started"})

    def _handle_export(self, payload: dict[str, Any]) -> Response:
        assert self._worker is not None
        output_path = payload.get("output_path")
        if not output_path:
            return Response(success=False, error="Missing 'output_path' in payload")
        include_errors = payload.get("include_errors", False)
        started = self._worker.start_export(
            Path(output_path), include_errors=include_errors
        )
        if not started:
            return Response(success=False, error="Worker is busy")
        return Response(success=True, data={"message": "Export started"})

    def _handle_status(self, payload: dict[str, Any]) -> Response:
        assert self._worker is not None
        return Response(success=True, data=self._worker.get_status())

    def _handle_pause(self, payload: dict[str, Any]) -> Response:
        assert self._worker is not None
        self._worker.pause()
        return Response(success=True, data={"message": "Paused"})

    def _handle_resume(self, payload: dict[str, Any]) -> Response:
        assert self._worker is not None
        self._worker.resume()
        return Response(success=True, data={"message": "Resumed"})

    def _handle_reset(self, payload: dict[str, Any]) -> Response:
        assert self._worker is not None
        assert self._db is not None
        # Gracefully stop any running operation first
        if self._worker.is_busy:
            log.info("Stopping running operation before reset …")
            self._worker.stop()
        self._db.reset()
        return Response(success=True, data={"message": "Database reset"})

    def _handle_stop(self, payload: dict[str, Any]) -> Response:
        self._running = False
        return Response(success=True, data={"message": "Daemon stopping"})

    def _handle_ping(self, payload: dict[str, Any]) -> Response:
        return Response(success=True, data={"message": "pong"})

    # ── Signal handling ──────────────────────────────────────────────

    def _handle_signal(self, signum: int, frame: Any) -> None:
        """Handle SIGTERM / SIGINT gracefully."""
        log.info("Received signal %d", signum)
        self._running = False


# ── Daemonize helper ─────────────────────────────────────────────────


def _daemonize() -> None:
    """Double-fork to detach from the controlling terminal."""
    if os.fork() > 0:
        sys.exit(0)
    os.setsid()
    if os.fork() > 0:
        sys.exit(0)
    # Redirect stdio to /dev/null
    sys.stdin = open(os.devnull)  # noqa: SIM115
    sys.stdout = open(os.devnull, "w")  # noqa: SIM115
    sys.stderr = open(os.devnull, "w")  # noqa: SIM115
