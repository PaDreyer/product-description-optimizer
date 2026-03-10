"""Tests for daemon components — PID management, worker lifecycle, and server."""

from __future__ import annotations

import os
import socket
import tempfile
import threading
import time
from pathlib import Path

import pytest

from pdo.core.db import Database
from pdo.daemon.pid import is_daemon_running, read_pid, remove_pid, write_pid
from pdo.daemon.worker import Worker
from pdo.protocol.messages import Request, Response, receive_message, send_message
from unittest.mock import patch

# ── PID management ───────────────────────────────────────────────────


class TestPidManagement:
    def test_write_and_read_pid(self, tmp_path: Path) -> None:
        pid_file = tmp_path / "test.pid"
        write_pid(pid_file)
        assert read_pid(pid_file) == os.getpid()

    def test_read_pid_missing_file(self, tmp_path: Path) -> None:
        assert read_pid(tmp_path / "nonexistent.pid") is None

    def test_read_pid_invalid_content(self, tmp_path: Path) -> None:
        pid_file = tmp_path / "bad.pid"
        pid_file.write_text("not-a-number")
        assert read_pid(pid_file) is None

    def test_is_daemon_running_detects_current_process(
        self, tmp_path: Path
    ) -> None:
        pid_file = tmp_path / "test.pid"
        write_pid(pid_file)
        assert is_daemon_running(pid_file) is True

    def test_is_daemon_running_stale_pid(self, tmp_path: Path) -> None:
        pid_file = tmp_path / "stale.pid"
        # Use a very high PID that almost certainly doesn't exist
        pid_file.write_text("99999999")
        assert is_daemon_running(pid_file) is False

    def test_is_daemon_running_no_file(self, tmp_path: Path) -> None:
        assert is_daemon_running(tmp_path / "nope.pid") is False

    def test_remove_pid(self, tmp_path: Path) -> None:
        pid_file = tmp_path / "test.pid"
        write_pid(pid_file)
        assert pid_file.exists()
        remove_pid(pid_file)
        assert not pid_file.exists()

    def test_remove_pid_missing_file(self, tmp_path: Path) -> None:
        """Should not raise if the file doesn't exist."""
        remove_pid(tmp_path / "nonexistent.pid")


# ── Worker lifecycle ─────────────────────────────────────────────────


@pytest.fixture()
def db() -> Database:
    database = Database(":memory:")
    database.initialize()
    return database


def _seed_products(db: Database, count: int = 3) -> None:
    db.insert_products([
        {
            "source_row_number": i + 1,
            "raw_data": {"name": f"Product {i}"},
            "product_id_value": f"P{i:04d}",
            "original_description": f"Description for product {i}",
            "context_data": {"Marke": f"Brand{i}"},
        }
        for i in range(count)
    ])


class TestWorker:
    def test_not_busy_initially(self, db: Database) -> None:
        worker = Worker(db)
        assert worker.is_busy is False

    def test_start_optimization(self, db: Database) -> None:
        _seed_products(db, 3)
        worker = Worker(db)
        assert worker.start_optimization() is True
        # Wait for completion
        time.sleep(0.5)
        assert worker.is_busy is False
        status = worker.get_status()
        assert status["last_result"]["succeeded"] == 3

    def test_reject_when_busy(self, db: Database) -> None:
        _seed_products(db, 100)
        worker = Worker(db)
        worker.start_optimization()
        # Should reject a second operation
        assert worker.start_optimization() is False
        worker.stop()

    def test_stop_event(self, db: Database) -> None:
        _seed_products(db, 50)
        worker = Worker(db)
        worker.start_optimization()
        worker.stop(timeout=2.0)
        assert worker.is_busy is False

    def test_get_status(self, db: Database) -> None:
        worker = Worker(db)
        status = worker.get_status()
        assert "busy" in status
        assert "stage" in status
        assert "progress" in status

    def test_pause_resume(self, db: Database) -> None:
        _seed_products(db, 5)
        worker = Worker(db)
        worker.start_optimization()
        worker.pause()
        status = worker.get_status()
        assert status["paused"] is True
        worker.resume()
        time.sleep(0.5)
        worker.stop(timeout=2.0)


# ── Server dispatch (unit-level) ─────────────────────────────────────


class TestServerDispatch:
    """Test the server's dispatch table by running it on a local socket."""

    def test_ping_pong(self, tmp_path: Path) -> None:
        """Start a minimal server and send a ping."""
        from pdo.daemon.server import DaemonServer

        # Use a short /tmp path for AF_UNIX
        fd, sock_file = tempfile.mkstemp(suffix=".sock", dir="/tmp")
        os.close(fd)
        os.unlink(sock_file)
        sock_path = Path(sock_file)

        config = _test_config(tmp_path)
        # Override socket_path to the short path
        from pdo.config import PdoConfig

        config = PdoConfig(
            data_dir=config.data_dir,
            log_dir=config.log_dir,
            socket_path=sock_path,
            config_file_path=config.config_file_path,
        )

        daemon = DaemonServer(config=config)

        config.data_dir.mkdir(parents=True, exist_ok=True)
        config.log_dir.mkdir(parents=True, exist_ok=True)

        db = Database(config.data_dir / "pdo.db")
        db.initialize()
        daemon._db = db
        daemon._worker = Worker(db)

        # Create socket
        server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server_sock.bind(str(sock_path))
        server_sock.listen(1)

        response_holder: list[Response] = []

        def _handle() -> None:
            conn, _ = server_sock.accept()
            try:
                conn.settimeout(2.0)
                raw = receive_message(conn)
                request = Request(**raw)
                resp = daemon._dispatch(request)
                send_message(conn, resp)
            finally:
                conn.close()

        t = threading.Thread(target=_handle)
        t.start()

        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(str(sock_path))
        send_message(client, Request(action="ping"))
        resp_raw = receive_message(client)
        resp = Response(**resp_raw)
        response_holder.append(resp)
        client.close()

        t.join(timeout=2.0)
        server_sock.close()
        db.close()
        sock_path.unlink(missing_ok=True)

        assert response_holder[0].success is True
        assert response_holder[0].data["message"] == "pong"

    def test_unknown_action(self, tmp_path: Path) -> None:
        from pdo.daemon.server import DaemonServer

        config = _test_config(tmp_path)
        daemon = DaemonServer(config=config)
        db = Database(":memory:")
        db.initialize()
        daemon._db = db
        daemon._worker = Worker(db)

        resp = daemon._dispatch(Request(action="nonexistent"))
        assert resp.success is False
        assert "Unknown action" in resp.error

        db.close()

    def test_status_action(self, tmp_path: Path) -> None:
        from pdo.daemon.server import DaemonServer

        config = _test_config(tmp_path)
        daemon = DaemonServer(config=config)
        db = Database(":memory:")
        db.initialize()
        daemon._db = db
        daemon._worker = Worker(db)

        resp = daemon._dispatch(Request(action="status"))
        assert resp.success is True
        assert "stage" in resp.data
        assert "progress" in resp.data

        db.close()

    def test_optimize_action_with_payload(self, tmp_path: Path) -> None:
        from pdo.daemon.server import DaemonServer

        config = _test_config(tmp_path)
        daemon = DaemonServer(config=config)
        db = Database(":memory:")
        db.initialize()
        daemon._db = db
        daemon._worker = Worker(db)

        with patch.object(daemon._worker, "start_optimization", return_value=True) as mock_start:
            resp = daemon._dispatch(Request(
                action="optimize",
                payload={"optimizer": "dummy", "api_key": "test_key"}
            ))

        assert resp.success is True
        mock_start.assert_called_once_with(optimizer_name="dummy", api_key="test_key")

        db.close()


def _test_config(tmp_path: Path):
    """Create a PdoConfig pointing at temp dirs."""
    from pdo.config import PdoConfig

    return PdoConfig(
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        socket_path=tmp_path / "pdo.sock",
        config_file_path=tmp_path / "config.toml",
    )
