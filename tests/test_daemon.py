"""Tests for daemon components — PID management, worker lifecycle, and server."""

from __future__ import annotations

import os
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from pdo.config import PdoConfig
from pdo.core.db import Database
from pdo.core.importer import ImportResult
from pdo.core.instance_lock import InstanceLock
from pdo.daemon.lifecycle import clean_stale_runtime
from pdo.daemon.pid import is_daemon_running, read_pid, remove_pid, write_pid
from pdo.daemon.worker import Worker
from pdo.exceptions import InstanceAlreadyRunningError
from pdo.protocol.messages import Request, Response, receive_message, send_message

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

    def test_is_daemon_running_detects_current_process(self, tmp_path: Path) -> None:
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

    def test_windows_liveness_check_does_not_send_signal(self, tmp_path: Path) -> None:
        with (
            patch("pdo.daemon.pid.read_pid", return_value=123),
            patch("pdo.daemon.pid.os") as fake_os,
            patch("pdo.daemon.pid._windows_process_alive", return_value=True) as alive,
        ):
            fake_os.name = "nt"
            assert is_daemon_running(tmp_path / "daemon.pid") is True
            fake_os.kill.assert_not_called()
            alive.assert_called_once_with(123)

    def test_remove_pid(self, tmp_path: Path) -> None:
        pid_file = tmp_path / "test.pid"
        write_pid(pid_file)
        assert pid_file.exists()
        remove_pid(pid_file)
        assert not pid_file.exists()

    def test_remove_pid_missing_file(self, tmp_path: Path) -> None:
        """Should not raise if the file doesn't exist."""
        remove_pid(tmp_path / "nonexistent.pid")

    def test_pid_reuse_marker_rejects_different_process(self, tmp_path: Path) -> None:
        from pdo.daemon import pid as pid_module

        pid_file = tmp_path / "daemon.pid"
        with patch.object(pid_module, "_process_marker", return_value="started:first"):
            write_pid(pid_file)
        with patch.object(pid_module, "_process_marker", return_value="started:reused"):
            assert read_pid(pid_file) is None
            assert pid_module.send_signal(pid_file) is False


def test_runtime_files_survive_when_data_directory_is_locked(tmp_path: Path) -> None:
    """Repair must not erase the endpoint of a process that still owns the DB."""
    config = PdoConfig(
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        config_file_path=tmp_path / "config.toml",
    )
    config.data_dir.mkdir()
    endpoint = config.data_dir / "daemon.endpoint"
    endpoint.write_text("active")
    pid_file = config.data_dir / "daemon.pid"
    pid_file.write_text("active")
    owner = InstanceLock(config.data_dir / "pdo.lock")
    owner.acquire()
    try:
        with pytest.raises(InstanceAlreadyRunningError):
            clean_stale_runtime(config)
        assert endpoint.read_text() == "active"
        assert pid_file.read_text() == "active"
    finally:
        owner.release()


# ── Worker lifecycle ─────────────────────────────────────────────────


@pytest.fixture()
def db() -> Iterator[Database]:
    with Database(":memory:") as database:
        database.initialize()
        yield database


def _seed_products(db: Database, count: int = 3) -> None:
    db.insert_products(
        [
            {
                "source_row_number": i + 1,
                "raw_data": {"name": f"Product {i}"},
                "product_id_value": f"P{i:04d}",
                "original_description": f"Description for product {i}",
                "context_data": {"Marke": f"Brand{i}"},
            }
            for i in range(count)
        ]
    )


class TestWorker:
    def test_not_busy_initially(self, db: Database) -> None:
        worker = Worker(db, PdoConfig())
        assert worker.is_busy is False

    def test_start_optimization(self, db: Database) -> None:
        _seed_products(db, 3)
        worker = Worker(db, PdoConfig())
        assert worker.start_optimization() is True
        # Wait for completion
        time.sleep(0.5)
        assert worker.is_busy is False
        status = worker.get_status()
        assert status["last_result"]["succeeded"] == 3

    def test_reject_when_busy(self, db: Database) -> None:
        _seed_products(db, 100)
        worker = Worker(db, PdoConfig())
        worker.start_optimization()
        # Should reject a second operation
        assert worker.start_optimization() is False
        worker.stop()

    def test_stop_event(self, db: Database) -> None:
        _seed_products(db, 50)
        worker = Worker(db, PdoConfig())
        worker.start_optimization()
        worker.stop(timeout=2.0)
        assert worker.is_busy is False

    def test_get_status(self, db: Database) -> None:
        worker = Worker(db, PdoConfig())
        status = worker.get_status()
        assert "busy" in status
        assert "stage" in status
        assert "progress" in status

    def test_pause_resume(self, db: Database) -> None:
        _seed_products(db, 5)
        worker = Worker(db, PdoConfig())
        worker.start_optimization()
        worker.pause()
        status = worker.get_status()
        assert status["paused"] is True
        worker.resume()
        time.sleep(0.5)
        worker.stop(timeout=2.0)

    def test_staged_import_reports_importing_while_busy(self, db: Database, tmp_path: Path) -> None:
        started = threading.Event()
        release = threading.Event()

        def slow_import(*args, **kwargs) -> ImportResult:
            started.set()
            assert release.wait(timeout=2.0)
            return ImportResult(total_rows=1, imported_count=1)

        worker = Worker(db, PdoConfig())
        with patch("pdo.daemon.worker.import_csv", side_effect=slow_import):
            assert worker.start_import(
                tmp_path / "unused.csv",
                [{"role": "description", "csv_column_name": "Description"}],
                replace_existing=True,
            )
            assert started.wait(timeout=2.0)
            status = worker.get_status()
            assert status["busy"] is True
            assert status["stage"] == "importing"
            release.set()
            worker.stop(timeout=2.0)


# ── Server dispatch (unit-level) ─────────────────────────────────────


class TestServerDispatch:
    """Test the server's dispatch table and loopback transport."""

    def test_ping_pong(self, tmp_path: Path) -> None:
        """Start a minimal server and send a ping."""
        from pdo.daemon.server import DaemonServer

        config = _test_config(tmp_path)
        daemon = DaemonServer(config=config)

        config.data_dir.mkdir(parents=True, exist_ok=True)
        config.log_dir.mkdir(parents=True, exist_ok=True)

        db = Database(config.data_dir / "pdo.db")
        db.initialize()
        daemon._db = db
        daemon._worker = Worker(db, config)

        # Create socket
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.bind(("127.0.0.1", 0))
        server_sock.listen(1)
        port = server_sock.getsockname()[1]

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

        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.connect(("127.0.0.1", port))
        send_message(client, Request(action="ping"))
        resp_raw = receive_message(client)
        resp = Response(**resp_raw)
        response_holder.append(resp)
        client.close()

        t.join(timeout=2.0)
        server_sock.close()
        db.close()

        assert response_holder[0].success is True
        assert response_holder[0].data["message"] == "pong"

    def test_unknown_action(self, tmp_path: Path) -> None:
        from pdo.daemon.server import DaemonServer

        config = _test_config(tmp_path)
        daemon = DaemonServer(config=config)
        db = Database(":memory:")
        db.initialize()
        daemon._db = db
        daemon._worker = Worker(db, config)

        resp = daemon._dispatch(Request(action="nonexistent"))
        assert resp.success is False
        assert "Unknown action" in resp.error

        db.close()

    def test_rejects_invalid_endpoint_token(self, tmp_path: Path) -> None:
        from pdo.daemon.server import DaemonServer

        config = _test_config(tmp_path)
        daemon = DaemonServer(config=config)
        db = Database(":memory:")
        db.initialize()
        daemon._db = db
        daemon._worker = Worker(db, config)
        daemon._auth_token = "expected-token"

        resp = daemon._dispatch(Request(action="ping", auth_token="wrong-token"))

        assert resp.success is False
        assert "authentication" in resp.error
        db.close()

    def test_status_action(self, tmp_path: Path) -> None:
        from pdo.daemon.server import DaemonServer

        config = _test_config(tmp_path)
        daemon = DaemonServer(config=config)
        db = Database(":memory:")
        db.initialize()
        daemon._db = db
        daemon._worker = Worker(db, config)

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
        daemon._worker = Worker(db, config)

        with patch.object(daemon._worker, "start_optimization", return_value=True) as mock_start:
            resp = daemon._dispatch(
                Request(
                    action="optimize",
                    payload={
                        "optimizer": "dummy",
                        "settings": {"style_instructions": "Concise"},
                    },
                )
            )

        assert resp.success is True
        mock_start.assert_called_once_with(optimizer_name="dummy")
        assert daemon._config.optimizer == "dummy"
        assert daemon._config.options["style_instructions"] == "Concise"

        db.close()

    def test_import_forwards_replacement_mode(self, tmp_path: Path) -> None:
        from pdo.daemon.server import DaemonServer

        config = _test_config(tmp_path)
        daemon = DaemonServer(config=config)
        db = Database(":memory:")
        db.initialize()
        daemon._db = db
        daemon._worker = Worker(db, config)

        with patch.object(daemon._worker, "start_import", return_value=True) as mock_start:
            resp = daemon._dispatch(
                Request(
                    action="import",
                    payload={
                        "csv_path": str(tmp_path / "products.csv"),
                        "column_mappings": [],
                        "delimiter": ",",
                        "replace_existing": True,
                    },
                )
            )

        assert resp.success is True
        mock_start.assert_called_once_with(
            tmp_path / "products.csv",
            [],
            delimiter=",",
            limit=None,
            replace_existing=True,
        )

        db.close()

    def test_products_action_returns_bounded_preview(self, tmp_path: Path) -> None:
        from pdo.daemon.server import DaemonServer

        config = _test_config(tmp_path)
        daemon = DaemonServer(config=config)
        db = Database(":memory:")
        db.initialize()
        _seed_products(db, 3)
        daemon._db = db
        daemon._worker = Worker(db, config)

        resp = daemon._dispatch(Request(action="products", payload={"limit": 2}))

        assert resp.success is True
        assert len(resp.data["products"]) == 2

        db.close()

    def test_product_payloads_stay_below_protocol_limit(self, tmp_path: Path) -> None:
        from pdo.daemon.server import DaemonServer

        config = _test_config(tmp_path)
        daemon = DaemonServer(config=config)
        db = Database(":memory:")
        db.initialize()
        huge = "\x01" * 1_100_000
        db.insert_products(
            [
                {
                    "source_row_number": 1,
                    "raw_data": {},
                    "product_id_value": huge,
                    "original_description": huge,
                }
            ]
        )
        db.update_product_status(1, "done", optimized_description=huge)
        daemon._db = db
        daemon._worker = Worker(db, config)

        preview = daemon._dispatch(Request(action="products"))
        detail = daemon._dispatch(Request(action="product", payload={"id": 1}))

        assert len(preview.to_json().encode("utf-8")) < 1_000_000
        assert len(detail.to_json().encode("utf-8")) < 1_000_000
        assert detail.data["product"]["original_truncated"] == 1
        assert detail.data["product"]["optimized_truncated"] == 1

        db.close()

    def test_product_list_byte_budget_handles_escaped_text(self, tmp_path: Path) -> None:
        from pdo.daemon.server import DaemonServer

        config = _test_config(tmp_path)
        daemon = DaemonServer(config=config)
        db = Database(":memory:")
        db.initialize()
        escaped = "\x01" * 1000
        db.insert_products(
            [
                {
                    "source_row_number": index,
                    "raw_data": {},
                    "product_id_value": escaped,
                    "original_description": escaped,
                }
                for index in range(1, 101)
            ]
        )
        for product_id in range(1, 101):
            db.update_product_status(
                product_id,
                "error",
                optimized_description=escaped,
                error_message=escaped,
            )
        daemon._db = db
        daemon._worker = Worker(db, config)

        response = daemon._dispatch(Request(action="products", payload={"limit": 1000}))

        assert len(response.data["products"]) == 100
        assert len(response.to_json().encode("utf-8")) < 1_000_000
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
