"""Local daemon server shared by CLI and desktop clients."""

from __future__ import annotations

import json
import logging
import os
import secrets
import selectors
import signal
import socket
import sys
import threading
import time
from collections.abc import Callable
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from pdo import __version__
from pdo.config import PdoConfig, load_config, save_config_values
from pdo.core.csv_format import CsvFormat
from pdo.core.db import Database
from pdo.core.error_groups import ERROR_GROUPS
from pdo.core.exporter import preview_csv
from pdo.core.instance_lock import InstanceLock
from pdo.daemon.endpoint import DaemonEndpoint, remove_endpoint, write_endpoint
from pdo.daemon.pid import remove_pid, write_pid
from pdo.daemon.worker import Worker
from pdo.protocol.messages import (
    PROTOCOL_REVISION,
    Request,
    Response,
    receive_message,
    send_message,
)

log = logging.getLogger(__name__)


class DaemonServer:
    """Loopback TCP server for the PDO daemon."""

    def __init__(self, config: PdoConfig | None = None) -> None:
        self._config = config or load_config()
        self._pid_path = self._config.data_dir / "daemon.pid"
        self._db: Database | None = None
        self._worker: Worker | None = None
        self._running = False
        self._server_sock: socket.socket | None = None
        self._sel: selectors.DefaultSelector | None = None
        self._instance_lock = InstanceLock(self._config.data_dir / "pdo.lock")
        self._pid_written = False
        self._port_published = False
        self._port: int | None = None
        self._auth_token: str | None = None

    # ── Lifecycle ────────────────────────────────────────────────────

    def start(self, *, on_ready: Callable[[], None] | None = None) -> None:
        """Start the daemon.

        Args:
            on_ready: Optional callback invoked when the endpoint is published.
        """
        self._instance_lock.acquire()
        try:
            self._setup()
            if not self._running:
                return
            if on_ready is not None:
                on_ready()
            log.info("Daemon started (pid=%d, port=%d)", os.getpid(), self._port)
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

        if self._port_published:
            remove_endpoint(self._config)
            self._port_published = False
        if self._pid_written:
            remove_pid(self._pid_path)
            self._pid_written = False

        if self._db:
            self._db.close()
            self._db = None

        self._instance_lock.release()

        log.info("Daemon stopped")

    # ── Internal setup ───────────────────────────────────────────────

    def _setup(self) -> None:
        """Initialise database, worker, endpoint, and signal handlers."""
        # Ensure directories exist
        self._config.data_dir.mkdir(parents=True, exist_ok=True)
        self._config.log_dir.mkdir(parents=True, exist_ok=True)

        # Configure logging
        log_file = self._config.log_dir / "daemon.log"
        handlers: list[logging.Handler] = [
            RotatingFileHandler(log_file, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
        ]
        if sys.stdout is not None:
            handlers.append(logging.StreamHandler(sys.stdout))
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            handlers=handlers,
            force=True,
        )

        # Database
        db_path = self._config.data_dir / "pdo.db"
        self._db = Database(db_path)
        self._db.initialize()
        self._db.requeue_processing()

        # Worker
        self._worker = Worker(self._db, self._config)

        # A loopback TCP endpoint works on Linux and Windows. Binding port 0
        # lets the OS select a free port, which is published after listen().
        remove_endpoint(self._config)
        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.bind(("127.0.0.1", 0))
        self._server_sock.listen(5)
        self._port = int(self._server_sock.getsockname()[1])
        self._auth_token = secrets.token_urlsafe(32)
        self._server_sock.setblocking(False)

        # Selector for non-blocking I/O
        self._sel = selectors.DefaultSelector()
        self._sel.register(self._server_sock, selectors.EVENT_READ)

        # Signal handlers
        self._running = True
        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGTERM, self._handle_signal)
            signal.signal(signal.SIGINT, self._handle_signal)

        write_pid(self._pid_path)
        self._pid_written = True
        write_endpoint(
            self._config,
            DaemonEndpoint(port=self._port, token=self._auth_token),
        )
        self._port_published = True

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
            raw = receive_message(conn, deadline=time.monotonic() + 1.0)
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

        if self._auth_token is not None and not secrets.compare_digest(
            request.auth_token, self._auth_token
        ):
            return Response(success=False, error="Daemon authentication failed.")

        # These authenticated control actions deliberately remain stable across
        # versions so a newly installed client can replace an older daemon.
        if request.action == "ping":
            return self._handle_ping(request.payload)
        if request.action == "stop":
            return self._handle_stop(request.payload)

        if request.client_version != __version__:
            return Response(
                success=False,
                error=(
                    f"Version mismatch: client is v{request.client_version}, "
                    f"but daemon is v{__version__}."
                ),
            )

        handlers: dict[str, Any] = {
            "import": self._handle_import,
            "optimize": self._handle_optimize,
            "export": self._handle_export,
            "status": self._handle_status,
            "products": self._handle_products,
            "product": self._handle_product,
            "settings": self._handle_settings,
            "export_preview": self._handle_export_preview,
            "pause": self._handle_pause,
            "resume": self._handle_resume,
            "reset": self._handle_reset,
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
        limit = payload.get("limit")
        started = self._worker.start_import(
            Path(csv_path),
            column_mappings,
            delimiter=delimiter,
            limit=limit,
            replace_existing=bool(payload.get("replace_existing", False)),
            **({"format_": CsvFormat.from_dict(payload["format"])} if "format" in payload else {}),
            **({"corrections": True} if payload.get("corrections") else {}),
        )
        if not started:
            return Response(success=False, error="Worker is busy")
        return Response(success=True, data={"message": "Import started"})

    def _handle_settings(self, payload: dict[str, Any]) -> Response:
        assert self._worker is not None
        if self._worker.is_busy:
            return Response(success=False, error="Worker is busy")
        optimizer_name = payload.get("optimizer")
        settings = payload.get("settings", {})
        if not isinstance(settings, dict):
            return Response(success=False, error="Invalid 'settings' in payload")
        if optimizer_name or settings:
            values = {str(key): str(value) for key, value in settings.items()}
            if optimizer_name:
                values["optimizer"] = str(optimizer_name)
            save_config_values(self._config.config_file_path, values)
            self._config = load_config(
                config_file=self._config.config_file_path,
                overrides={
                    "data_dir": str(self._config.data_dir),
                    "log_dir": str(self._config.log_dir),
                    "socket_path": str(self._config.socket_path),
                },
            )
            self._worker.update_config(self._config)
        return Response(success=True)

    def _handle_optimize(self, payload: dict[str, Any]) -> Response:
        assert self._worker is not None
        groups = payload.get("retry_groups")
        if groups is not None and (
            not isinstance(groups, list)
            or not groups
            or len(groups) > len(ERROR_GROUPS)
            or any(
                not isinstance(k, str) or k not in ERROR_GROUPS or not ERROR_GROUPS[k][1]
                for k in groups
            )
        ):
            return Response(success=False, error="Ungültige Auswahl wiederholbarer Fehlergruppen.")
        response = self._handle_settings(payload)
        if not response.success:
            return response
        started = self._worker.start_optimization(
            optimizer_name=payload.get("optimizer"),
            **({"retry_groups": groups} if groups is not None else {}),
        )
        if not started:
            return Response(success=False, error="Worker is busy")
        return Response(success=True, data={"message": "Optimization started"})

    def _handle_export(self, payload: dict[str, Any]) -> Response:
        assert self._worker is not None
        output_path = payload.get("output_path")
        if not output_path:
            return Response(success=False, error="Missing 'output_path' in payload")
        include_errors = payload.get("include_errors", False)
        format_ = CsvFormat.from_dict(payload["format"]) if "format" in payload else None
        scope = payload.get("scope")
        if scope is not None and scope not in {"done", "all", "completed", "errors", "corrections"}:
            return Response(success=False, error="Ungültiger Exportumfang.")
        if payload.get("remember_format") and format_:
            result = self._handle_settings(
                {"settings": {"export.format": json.dumps(format_.to_dict())}}
            )
            if not result.success:
                return result
        started = self._worker.start_export(
            Path(output_path),
            include_errors=include_errors,
            format_=format_,
            scope=scope,
        )
        if not started:
            return Response(success=False, error="Worker is busy")
        return Response(success=True, data={"message": "Export started"})

    def _handle_export_preview(self, payload: dict[str, Any]) -> Response:
        assert self._db is not None
        format_ = CsvFormat.from_dict(payload.get("format", {}))
        return Response(
            success=True,
            data={
                "text": preview_csv(self._db, format_, payload.get("scope", "done")),
            },
        )

    def _handle_status(self, payload: dict[str, Any]) -> Response:
        assert self._worker is not None
        return Response(success=True, data=self._worker.get_status())

    def _handle_products(self, payload: dict[str, Any]) -> Response:
        assert self._db is not None
        try:
            limit = max(0, min(int(payload.get("limit", 100)), 100))
        except (TypeError, ValueError):
            return Response(success=False, error="Invalid product limit")
        offset = max(0, int(payload.get("offset", 0)))
        status = payload.get("status")
        if status not in {None, "done", "pending", "processing", "error"}:
            return Response(success=False, error="Invalid product status")
        search = str(payload.get("search", ""))[:500]
        return Response(
            success=True,
            data={
                "products": self._db.get_product_preview(limit, offset, status, search),
                "total": self._db.count_products(status, search),
            },
        )

    def _handle_product(self, payload: dict[str, Any]) -> Response:
        assert self._db is not None
        try:
            product_id = int(payload["id"])
        except (KeyError, TypeError, ValueError):
            return Response(success=False, error="Invalid product ID")
        product = self._db.get_product_detail(product_id)
        if product is None:
            return Response(success=False, error="Product not found")
        return Response(success=True, data={"product": product})

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
        keep = payload.get("keep", False)
        # Gracefully stop any running operation first
        if self._worker.is_busy:
            log.info("Stopping running operation before reset …")
            self._worker.stop()
        self._worker.reset()
        self._db.reset(keep=keep)
        msg = "Products kept but flagged pending" if keep else "Database reset"
        return Response(success=True, data={"message": msg})

    def _handle_stop(self, payload: dict[str, Any]) -> Response:
        self._running = False
        return Response(success=True, data={"message": "Daemon stopping"})

    def _handle_ping(self, payload: dict[str, Any]) -> Response:
        return Response(
            success=True, data={"message": "pong", "protocol_revision": PROTOCOL_REVISION}
        )

    # ── Signal handling ──────────────────────────────────────────────

    def _handle_signal(self, signum: int, frame: Any) -> None:
        """Handle SIGTERM / SIGINT gracefully."""
        log.info("Received signal %d", signum)
        self._running = False
