"""Desktop client tests using a real shared daemon."""

from __future__ import annotations

import csv
import os
import socket
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, suppress
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pdo import __version__
from pdo.cli.client import send_command
from pdo.config import PdoConfig, load_config, save_config_values
from pdo.core.db import Database
from pdo.core.instance_lock import InstanceLock
from pdo.daemon.endpoint import endpoint_file, remove_endpoint
from pdo.daemon.pid import read_pid, wait_for_exit
from pdo.daemon.server import DaemonServer
from pdo.desktop.session import DesktopSession, inspect_csv, suggest_role
from pdo.exceptions import DaemonNotRunningError
from pdo.protocol.messages import Response, receive_message, send_message


@contextmanager
def _running_daemon(config: PdoConfig) -> Iterator[None]:
    daemon = DaemonServer(config)
    failures: list[BaseException] = []

    def run() -> None:
        try:
            daemon.start()
        except BaseException as exc:  # pragma: no cover - surfaced in parent
            failures.append(exc)

    thread = threading.Thread(target=run, name="test-pdo-daemon")
    thread.start()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if failures:
            raise failures[0]
        try:
            if send_command("ping", config=config).success:
                break
        except DaemonNotRunningError:
            time.sleep(0.02)
    else:
        raise AssertionError("Test daemon did not start")
    try:
        yield
    finally:
        with suppress(DaemonNotRunningError):
            send_command("stop", config=config)
        thread.join(timeout=5)
        assert not thread.is_alive()
        if failures:
            raise failures[0]


def _config(tmp_path: Path) -> PdoConfig:
    return PdoConfig(
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        socket_path=tmp_path / "pdo.sock",
        config_file_path=tmp_path / "config.toml",
    )


def _wait_for_job(session: DesktopSession) -> None:
    deadline = time.monotonic() + 5
    while session.status()["busy"] and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not session.status()["busy"]


def test_inspect_csv_detects_format_and_roles(tmp_path: Path) -> None:
    source = tmp_path / "products.csv"
    source.write_text("\ufeffSKU,Description,Brand\nA1,Blue bag,Example\n", encoding="utf-8")
    preview = inspect_csv(source)
    assert preview.headers == ["SKU", "Description", "Brand"]
    assert preview.delimiter == ","
    assert preview.rows[0] == ["A1", "Blue bag", "Example"]
    assert [suggest_role(header) for header in preview.headers] == [
        "product_id",
        "description",
        "context",
    ]


def test_config_settings_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    save_config_values(path, {"gemini.api_key": 'quoted"value', "optimizer": "gemini"})
    save_config_values(path, {"gemini.model": "gemini-3.6-flash"})
    config = load_config(config_file=path)
    assert config.options["gemini.api_key"] == 'quoted"value'
    assert config.options["gemini.model"] == "gemini-3.6-flash"
    if os.name != "nt":
        assert path.stat().st_mode & 0o077 == 0


def test_desktop_session_import_optimize_export(tmp_path: Path) -> None:
    config = _config(tmp_path)
    with _running_daemon(config):
        session = DesktopSession(config, auto_start=False)
        source = Path(__file__).parent / "fixtures" / "sample_products.csv"
        preview = inspect_csv(source)
        mappings = [
            {"role": role, "csv_column_name": header, "display_name": header}
            for header in preview.headers
            if (role := suggest_role(header)) != "ignore"
        ]
        session.import_file(preview, mappings)
        _wait_for_job(session)
        assert session.status()["progress"]["total"] == 10
        assert len(session.products(3)) == 3

        session.optimize("dummy", {})
        _wait_for_job(session)
        assert session.status()["progress"]["done"] == 10

        output = tmp_path / "result.csv"
        session.export_file(output)
        _wait_for_job(session)
        with output.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream, delimiter=";"))
        assert len(rows) == 10
        assert rows[0]["optimized_description"].startswith("[OPTIMIZED]")


def test_desktop_session_recovers_interrupted_product(tmp_path: Path) -> None:
    config = _config(tmp_path)
    config.data_dir.mkdir()
    with Database(config.data_dir / "pdo.db") as db:
        db.initialize()
        db.insert_products([{"source_row_number": 1, "raw_data": {}, "product_id_value": "A1"}])
        db.update_product_status(1, "processing")
        db.set_pipeline_state("optimizing")
    with _running_daemon(config):
        session = DesktopSession(config, auto_start=False)
        assert session.status()["progress"]["pending"] == 1
        assert session.status()["stage"] == "idle"


def test_two_desktop_clients_share_the_daemon(tmp_path: Path) -> None:
    config = _config(tmp_path)
    with _running_daemon(config):
        first = DesktopSession(config, auto_start=False)
        second = DesktopSession(config, auto_start=False)
        source = tmp_path / "products.csv"
        source.write_text("ID;Description\nA1;Shared text\n", encoding="utf-8")
        preview = inspect_csv(source)
        mappings = [
            {"role": "product_id", "csv_column_name": "ID", "display_name": "ID"},
            {
                "role": "description",
                "csv_column_name": "Description",
                "display_name": "Description",
            },
        ]
        first.import_file(preview, mappings)
        _wait_for_job(second)
        assert second.products()[0]["original_description"] == "Shared text"
        first.close()
        assert second.status()["progress"]["total"] == 1


def test_desktop_auto_starts_daemon_and_close_leaves_it_running(tmp_path: Path) -> None:
    config = _config(tmp_path)
    session = DesktopSession(config)
    try:
        assert session.status()["stage"] == "idle"
        session.close()
        assert send_command("ping", config=config).success
    finally:
        with suppress(DaemonNotRunningError):
            send_command("stop", config=config)
        deadline = time.monotonic() + 5
        while endpoint_file(config).exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not endpoint_file(config).exists()


def test_daemon_launcher_replaces_outdated_daemon(tmp_path: Path) -> None:
    from pdo.daemon.launcher import ensure_daemon_running

    config = _config(tmp_path)
    ensure_daemon_running(config)
    old_pid = read_pid(config.data_dir / "daemon.pid")
    assert old_pid is not None
    original_send_command = send_command
    first_ping = True

    def pretend_old_version(action: str, *args: object, **kwargs: object) -> Response:
        nonlocal first_ping
        if action == "ping" and first_ping:
            first_ping = False
            return Response(success=True, server_version="0.1.0")
        return original_send_command(action, *args, **kwargs)

    try:
        with patch("pdo.daemon.launcher.send_command", side_effect=pretend_old_version):
            ensure_daemon_running(config)
        new_pid = read_pid(config.data_dir / "daemon.pid")
        assert new_pid is not None and new_pid != old_pid
        assert send_command("ping", config=config).server_version == __version__
    finally:
        with suppress(DaemonNotRunningError):
            send_command("stop", config=config)


def test_daemon_launcher_recovers_missing_endpoint(tmp_path: Path) -> None:
    """A live daemon with a deleted endpoint must not block GUI startup."""
    from pdo.daemon.launcher import ensure_daemon_running

    config = _config(tmp_path)
    ensure_daemon_running(config)
    old_pid = read_pid(config.data_dir / "daemon.pid")
    assert old_pid is not None
    remove_endpoint(config)
    try:
        ensure_daemon_running(config)
        new_pid = read_pid(config.data_dir / "daemon.pid")
        assert new_pid is not None and new_pid != old_pid
        assert wait_for_exit(old_pid, 0)
        assert send_command("ping", config=config).success
    finally:
        with suppress(DaemonNotRunningError):
            send_command("stop", config=config)


def test_simultaneous_clients_share_one_new_daemon(tmp_path: Path) -> None:
    """Two clients launched together must attach to the same process."""
    from pdo.daemon.launcher import ensure_daemon_running

    config = _config(tmp_path)
    barrier = threading.Barrier(3)

    def connect() -> int | None:
        barrier.wait(timeout=5)
        ensure_daemon_running(config)
        return read_pid(config.data_dir / "daemon.pid")

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(connect) for _ in range(2)]
            barrier.wait(timeout=5)
            pids = [future.result(timeout=20) for future in futures]
        assert pids[0] is not None and pids[0] == pids[1]
        assert send_command("ping", config=config).success
    finally:
        with suppress(DaemonNotRunningError):
            send_command("stop", config=config)


def test_daemon_launcher_reports_child_startup_error(tmp_path: Path) -> None:
    """A failing daemon reports its error immediately through the startup channel."""
    from pdo.daemon.launcher import ensure_daemon_running

    config = _config(tmp_path)
    config.data_dir.mkdir()
    (config.data_dir / "pdo.db").mkdir()
    with pytest.raises(RuntimeError, match=r"database|directory|open"):
        ensure_daemon_running(config, timeout=2)
    assert not endpoint_file(config).exists()
    assert read_pid(config.data_dir / "daemon.pid") is None


def test_quit_stops_daemon_when_endpoint_is_missing(tmp_path: Path) -> None:
    """The Quit action must not leave an undiscoverable daemon running."""
    config = _config(tmp_path)
    session = DesktopSession(config)
    pid = read_pid(config.data_dir / "daemon.pid")
    assert pid is not None
    remove_endpoint(config)
    session.stop_daemon()
    assert wait_for_exit(pid, 0)
    assert not endpoint_file(config).exists()
    assert read_pid(config.data_dir / "daemon.pid") is None


@pytest.mark.skipif(os.name == "nt", reason="Legacy daemon used Unix sockets only")
def test_legacy_daemon_upgrade_uses_old_protocol_and_waits_for_lock(tmp_path: Path) -> None:
    from pdo.daemon.launcher import _stop_legacy_daemon

    config = _config(tmp_path)
    lock = InstanceLock(config.data_dir / "pdo.lock")
    lock.acquire()
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(config.socket_path))
    listener.listen(1)
    listener.settimeout(3)
    requests: list[dict[str, object]] = []

    def serve() -> None:
        try:
            for response in (
                Response(
                    success=False, error="Version mismatch: old daemon", server_version="0.1.0"
                ),
                Response(success=True, data={"message": "pong"}, server_version="0.1.0"),
                Response(success=True, data={"message": "Daemon stopping"}, server_version="0.1.0"),
            ):
                connection, _ = listener.accept()
                with connection:
                    requests.append(receive_message(connection))
                    send_message(connection, response)
        finally:
            lock.release()
            listener.close()
            config.socket_path.unlink(missing_ok=True)

    thread = threading.Thread(target=serve)
    thread.start()

    def await_legacy_exit(pid: int, timeout: float) -> bool:
        assert pid == 123
        thread.join(timeout=timeout)
        return not thread.is_alive()

    try:
        with (
            patch("pdo.daemon.launcher.read_pid", return_value=123),
            patch("pdo.daemon.launcher.wait_for_exit", side_effect=await_legacy_exit),
        ):
            _stop_legacy_daemon(config, timeout=3)
    finally:
        thread.join(timeout=4)
        assert not thread.is_alive()
    assert [request["action"] for request in requests] == ["ping", "ping", "stop"]
    assert [request["client_version"] for request in requests] == [__version__, "0.1.0", "0.1.0"]
    assert all("auth_token" not in request for request in requests)


def test_explicit_stop_is_not_undone_by_second_desktop_client(tmp_path: Path) -> None:
    config = _config(tmp_path)
    with _running_daemon(config):
        first = DesktopSession(config, auto_start=False)
        second = DesktopSession(config)
        first.stop_daemon()
        deadline = time.monotonic() + 5
        while endpoint_file(config).exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not endpoint_file(config).exists()
        with pytest.raises(DaemonNotRunningError):
            second.status()
        assert not endpoint_file(config).exists()


def test_daemon_launcher_uses_source_entry_without_desktop_dependency(tmp_path: Path) -> None:
    from pdo.daemon.launcher import _daemon_command

    config = _config(tmp_path)
    with patch.dict(os.environ, {}, clear=True):
        command = _daemon_command(config)
    assert command[1:3] == ["-m", "pdo.daemon.entry"]
    assert "--daemon-process" in command
    assert "--ready-token=-leading" in _daemon_command(
        config, ready_port=1234, ready_token="-leading"
    )


def test_daemon_entry_runs_foreground_with_shared_directories(tmp_path: Path) -> None:
    from pdo.daemon.entry import main as daemon_main

    config = _config(tmp_path)
    arguments = [
        "--daemon-process",
        "--daemon-config",
        str(config.config_file_path),
        "--daemon-data-dir",
        str(config.data_dir),
        "--daemon-log-dir",
        str(config.log_dir),
    ]
    with patch("pdo.daemon.entry.DaemonServer") as server:
        assert daemon_main(arguments) == 0
    server.assert_called_once()
    started_config = server.call_args.args[0]
    assert started_config.data_dir == config.data_dir
    assert started_config.log_dir == config.log_dir
    server.return_value.start.assert_called_once()
    assert callable(server.return_value.start.call_args.kwargs["on_ready"])


def test_failed_replacement_import_preserves_current_batch(tmp_path: Path) -> None:
    config = _config(tmp_path)
    with _running_daemon(config):
        session = DesktopSession(config, auto_start=False)
        source = tmp_path / "first.csv"
        source.write_text("ID;Description\nA1;Existing text\n", encoding="utf-8")
        preview = inspect_csv(source)
        mappings = [
            {"role": "product_id", "csv_column_name": "ID", "display_name": "ID"},
            {
                "role": "description",
                "csv_column_name": "Description",
                "display_name": "Description",
            },
        ]
        session.import_file(preview, mappings)
        _wait_for_job(session)
        assert session.products()[0]["original_description"] == "Existing text"

        invalid = tmp_path / "invalid.csv"
        invalid.write_text("ID1;ID2;Description\nA1\n", encoding="utf-8")
        invalid_preview = inspect_csv(invalid)
        invalid_mappings = [
            {"role": "product_id", "csv_column_name": "ID1", "display_name": "ID1"},
            {"role": "product_id", "csv_column_name": "ID2", "display_name": "ID2"},
            {
                "role": "description",
                "csv_column_name": "Description",
                "display_name": "Description",
            },
        ]
        session.import_file(invalid_preview, invalid_mappings)
        _wait_for_job(session)

        result = session.status()["last_result"]
        assert "No product rows were imported" in result["error"]
        assert session.status()["progress"]["total"] == 1
        assert session.products()[0]["original_description"] == "Existing text"

        replacement = tmp_path / "replacement.csv"
        replacement.write_text("ID;Description\nB1;Replacement text\n", encoding="utf-8")
        failed_preview = inspect_csv(replacement)
        replacement.unlink()
        session.import_file(failed_preview, mappings)
        _wait_for_job(session)

        assert "error" in session.status()["last_result"]
        assert session.status()["progress"]["total"] == 1
        assert session.products()[0]["original_description"] == "Existing text"


def test_desktop_window_runs_guided_workflow_offscreen(tmp_path: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from pdo.desktop.app import DesktopWindow

    app = QApplication.instance() or QApplication([])
    config = _config(tmp_path)
    with _running_daemon(config):
        window = DesktopWindow(DesktopSession(config, auto_start=False))
        try:
            assert window.windowTitle().startswith("PDO")
            assert window.pages.count() == 4

            source = tmp_path / "products.csv"
            source.write_text("SKU,Description,Brand\nA1,Blue bag,Example\n", encoding="utf-8")
            with patch(
                "pdo.desktop.app.QFileDialog.getOpenFileName",
                return_value=(str(source), "CSV files (*.csv)"),
            ):
                window._choose_source()
            assert window.sample_table.rowCount() == 1
            assert len(window._mapping_boxes) == 3

            for backend, expected_text in (
                ("gemini", "cloud provider"),
                ("local_llm", "server address"),
                ("dummy", "on this computer"),
            ):
                window.backend_box.setCurrentIndex(window.backend_box.findData(backend))
                assert expected_text in window.data_flow_label.text()

            window._start_import()
            _wait_for_job(window.session)
            window._poll()
            assert window.results_table.rowCount() == 1

            window.backend_box.setCurrentIndex(window.backend_box.findData("dummy"))
            window._start_optimization()
            _wait_for_job(window.session)
            window._poll()
            window.results_table.selectRow(0)
            window._show_selected_product()
            assert "[OPTIMIZED]" in window.detail.toPlainText()

            output = tmp_path / "output.csv"
            window.output_path.setText(str(output))
            window._start_export()
            _wait_for_job(window.session)
            window._poll()
            app.processEvents()
            assert output.is_file()
        finally:
            window._exit_gui()


def test_window_close_hides_to_tray_without_stopping_daemon(tmp_path: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QSystemTrayIcon

    from pdo.desktop.app import DesktopWindow

    app = QApplication.instance() or QApplication([])
    config = _config(tmp_path)
    tray = MagicMock()
    with _running_daemon(config):
        with patch.object(DesktopWindow, "_create_tray", return_value=tray):
            window = DesktopWindow(DesktopSession(config, auto_start=False))
        window.show()
        app.processEvents()
        window.close()
        app.processEvents()
        assert not window.isVisible()
        tray.notify.assert_called_once()
        assert send_command("ping", config=config).success
        window._tray_activated(QSystemTrayIcon.ActivationReason.Trigger)
        assert window.isVisible()
        window.close()
        assert not window.isVisible()
        tray.available = False
        window._poll()
        assert window.isVisible()
        tray.available = True
        window.close()
        assert not window.isVisible()
        tray.available = False
        window._poll()
        assert window.isVisible()
        window._exit_gui()


def test_tray_quit_stops_daemon_and_gui(tmp_path: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from pdo.desktop.app import DesktopWindow

    app = QApplication.instance() or QApplication([])
    config = _config(tmp_path)
    tray = MagicMock()
    tray.available = True
    with _running_daemon(config):
        with patch.object(DesktopWindow, "_create_tray", return_value=tray):
            window = DesktopWindow(DesktopSession(config, auto_start=False))
        window.show()
        app.processEvents()
        window.close()
        assert not window.isVisible()
        assert send_command("ping", config=config).success
        menu = window._build_qt_tray_menu()
        assert [action.text() for action in menu.actions()] == ["Open", "Quit"]
        menu.actions()[0].trigger()
        app.processEvents()
        assert window.isVisible()
        assert send_command("ping", config=config).success
        window.close()
        assert not window.isVisible()
        menu.actions()[-1].trigger()
        deadline = time.monotonic() + 5
        while endpoint_file(config).exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not endpoint_file(config).exists()
        assert not window.isVisible()


def test_tray_quit_keeps_gui_open_if_daemon_rejects_stop(tmp_path: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from pdo.desktop.app import DesktopWindow

    app = QApplication.instance() or QApplication([])
    config = _config(tmp_path)
    tray = MagicMock()
    tray.available = True
    with _running_daemon(config):
        with patch.object(DesktopWindow, "_create_tray", return_value=tray):
            window = DesktopWindow(DesktopSession(config, auto_start=False))
        window.show()
        app.processEvents()
        window.close()
        assert not window.isVisible()
        with (
            patch.object(window.session, "stop_daemon", side_effect=RuntimeError("stop failed")),
            patch.object(window, "_error") as show_error,
        ):
            window.quit()
        assert window.isVisible()
        show_error.assert_called_once()
        assert "stop failed" in show_error.call_args.args[0]
        window._exit_gui()


def test_window_close_quits_gui_when_tray_is_unavailable(tmp_path: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from pdo.desktop.app import DesktopWindow

    app = QApplication.instance() or QApplication([])
    config = _config(tmp_path)
    with _running_daemon(config):
        with patch.object(DesktopWindow, "_create_tray", return_value=None):
            window = DesktopWindow(DesktopSession(config, auto_start=False))
        with patch.object(app, "quit") as quit_app:
            window.close()
        quit_app.assert_called_once()
        assert send_command("ping", config=config).success


def test_window_close_quits_gui_after_tray_host_disappears(tmp_path: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from pdo.desktop.app import DesktopWindow

    app = QApplication.instance() or QApplication([])
    config = _config(tmp_path)
    tray = MagicMock()
    tray.available = False
    with _running_daemon(config):
        with patch.object(DesktopWindow, "_create_tray", return_value=tray):
            window = DesktopWindow(DesktopSession(config, auto_start=False))
        with patch.object(app, "quit") as quit_app:
            window.close()
        quit_app.assert_called_once()
        tray.stop.assert_called_once()
        assert send_command("ping", config=config).success
