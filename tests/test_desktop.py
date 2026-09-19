"""Desktop client tests using a real shared daemon."""

from __future__ import annotations

import csv
import os
import socket
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import TYPE_CHECKING
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

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication


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


@pytest.mark.parametrize("same_version", [False, True])
def test_daemon_launcher_replaces_outdated_daemon(tmp_path: Path, same_version: bool) -> None:
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
            return Response(success=True, server_version=__version__ if same_version else "0.1.0")
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


def test_desktop_window_runs_guided_workflow_offscreen(tmp_path: Path, qapp: QApplication) -> None:
    from pdo.desktop.app import DesktopWindow

    config = _config(tmp_path)
    with _running_daemon(config):
        window = DesktopWindow(DesktopSession(config, auto_start=False))
        try:
            assert window.windowTitle().startswith("PDO")
            assert window.pages.count() == 5

            source = tmp_path / "products.csv"
            source.write_text("SKU,Description,Brand\nA1,Blue bag,Example\n", encoding="utf-8")
            with patch(
                "pdo.desktop.app.QFileDialog.getOpenFileName",
                return_value=(str(source), "CSV files (*.csv)"),
            ):
                window._choose_source()
            assert window.sample_table.rowCount() == 3
            assert len(window._mapping_boxes) == 3

            for backend, expected_text in (
                ("gemini", "Google Gemini"),
                ("local_llm", "Serveradresse"),
                ("dummy", "auf diesem Computer"),
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
            with patch(
                "pdo.desktop.app.QFileDialog.getSaveFileName", return_value=(str(output), "CSV")
            ):
                window._start_export()
            _wait_for_job(window.session)
            window._poll()
            qapp.processEvents()
            assert output.is_file()
        finally:
            window._exit_gui()


def _process_until(qapp: QApplication, condition: Callable[[], bool]) -> None:
    """Wait for a GUI callback without blocking Qt event delivery."""
    deadline = time.monotonic() + 3
    while not condition() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    assert condition()


def test_provider_settings_only_request_relevant_fields(tmp_path: Path, qapp: QApplication) -> None:
    from pdo.desktop.app import DesktopWindow

    config = _config(tmp_path)
    with _running_daemon(config), patch.object(DesktopWindow, "_create_tray", return_value=None):
        window = DesktopWindow(DesktopSession(config, auto_start=False))
        try:
            window.show()
            window._open_settings()
            for provider in ("gemini", "zhipuai"):
                window.backend_box.setCurrentIndex(window.backend_box.findData(provider))
                assert window.key_input.isVisible()
                assert not window.address_input.isVisible()
                assert not window.model_input.isVisible()
                window.manual_model.setChecked(True)
                assert window.model_input.isVisible()
                window.model_input.setText("my-custom-model")
                assert window._provider_settings()[f"{provider}.model"] == "my-custom-model"
                window.manual_model.setChecked(False)
            window.backend_box.setCurrentIndex(window.backend_box.findData("dummy"))
            assert not window.key_input.isVisible()
            assert not window.model_input.isVisible()
            assert not window.address_input.isVisible()
            assert not window.manual_model.isVisible()
            window.backend_box.setCurrentIndex(window.backend_box.findData("local_llm"))
            assert window.address_input.isVisible()
            assert not window.key_input.isVisible()
            with patch.object(window.session, "models", return_value=["only-loaded-model"]):
                window._check_connection()
                _process_until(qapp, lambda: window._models == ["only-loaded-model"])
            assert not window.model_box.isVisible()
            assert not window.model_input.isVisible()
            assert window._provider_settings()["local_llm.model"] == "only-loaded-model"
            with patch.object(window.session, "models", return_value=["one", "two"]):
                window._check_connection()
                _process_until(qapp, lambda: window._models == ["one", "two"])
            assert window.model_box.isVisible()
            window.model_box.setCurrentText("two")
            window._save_settings()
            assert (
                load_config(config_file=config.config_file_path).options["local_llm.model"] == "two"
            )
            window._open_settings()
            window.address_input.setText("http://localhost:5678/v1")
            assert window.connection_button.isEnabled()
            with pytest.raises(ValueError, match="Prüfe zuerst"):
                window._provider_settings()
            window._cancel_settings()
            assert window.address_input.text() == "http://127.0.0.1:11434/v1"
        finally:
            window._exit_gui()


def test_gui_error_groups_retry_correct_and_export_without_touching_successes(
    tmp_path: Path, qapp: QApplication
) -> None:
    from PySide6.QtCore import Qt

    from pdo.core.csv_format import CsvFormat
    from pdo.desktop.app import DesktopWindow

    config = _config(tmp_path)
    source = tmp_path / "source.csv"
    source.write_text("SKU;Description\nP1;Ready\nP2;Retry\nP3;\n", encoding="utf-8")
    with _running_daemon(config), patch.object(DesktopWindow, "_create_tray", return_value=None):
        session = DesktopSession(config, auto_start=False)
        session.import_file(
            inspect_csv(source),
            [
                {"role": "product_id", "csv_column_name": "SKU", "display_name": "SKU"},
                {
                    "role": "description",
                    "csv_column_name": "Description",
                    "display_name": "Description",
                },
            ],
        )
        _wait_for_job(session)
        session.optimize("dummy", {})
        _wait_for_job(session)
        with Database(config.data_dir / "pdo.db") as database:
            database.update_product_status(2, "error", error_message="Timed out")
        window = DesktopWindow(session)
        try:
            window.show()
            window.result_tabs.setCurrentIndex(1)
            assert window.errors_table.rowCount() == 2
            assert [g["kind"] for g in window._selected_groups()] == ["timeout"]
            window._select_all_errors(False)
            assert not window.retry_button.isEnabled()
            window._select_all_errors(True)
            assert window.retry_button.isEnabled()
            window._retry_errors()
            _wait_for_job(session)
            window._poll()
            assert session.status()["progress"]["done"] == 2
            assert session.status()["error_groups"][0]["kind"] == "missing_data"
            assert not window.retry_button.isEnabled()
            correction = tmp_path / "correction.csv"
            correction.write_text("SKU;Description\nP3;Ergänzte Beschreibung\n", encoding="utf-16")
            with patch(
                "pdo.desktop.app.QFileDialog.getOpenFileName", return_value=(str(correction), "CSV")
            ):
                window._import_corrections()
            _wait_for_job(session)
            window._poll()
            assert window._selected_groups()[0]["kind"] == "corrected"
            window._retry_errors()
            _wait_for_job(session)
            window._poll()
            assert session.status()["progress"]["done"] == 3
            assert session.product(1)["optimized_description"] == "[OPTIMIZED] READY"
            window.search_input.setText("P3")
            window._search_products()
            assert window.results_table.rowCount() == 1
            assert "ERGÄNZTE" in window.detail.toPlainText()
            window._open_export("done")
            format_ = CsvFormat(encoding="utf-16-le", delimiter="\t", bom=True)
            window.format_editor.set_format(format_)
            window.format_editor.remember.setChecked(True)
            window._refresh_export_preview()
            _process_until(qapp, lambda: window.save_button.isEnabled())
            output = tmp_path / "export.csv"
            with patch(
                "pdo.desktop.app.QFileDialog.getSaveFileName", return_value=(str(output), "CSV")
            ):
                window._start_export()
            _wait_for_job(session)
            window._poll()
            assert "Gespeichert:" in window.export_error.text()
            assert output.read_bytes().startswith(b"\xff\xfe")
            with output.open(encoding="utf-16", newline="") as stream:
                rows = list(csv.DictReader(stream, delimiter="\t"))
            assert len(rows) == 3
            assert rows[2]["optimized_description"] == "[OPTIMIZED] ERGÄNZTE BESCHREIBUNG"
            assert '"utf-16-le"' in session.config.options["export.format"]
            window.prepare_export_button.click()
            window.format_editor.delimiter.setCurrentIndex(5)
            window.format_editor.custom.setText("xx")
            window._refresh_export_preview()
            assert not window.save_button.isEnabled()
            assert "einzelne Zeichen" in window.export_error.text()
            assert window.select_errors.checkState() != Qt.CheckState.PartiallyChecked
        finally:
            window._exit_gui()


def test_old_poll_response_cannot_complete_a_new_action(tmp_path: Path, qapp: QApplication) -> None:
    from pdo.desktop.app import DesktopWindow

    config = _config(tmp_path)
    with _running_daemon(config), patch.object(DesktopWindow, "_create_tray", return_value=None):
        window = DesktopWindow(DesktopSession(config, auto_start=False))
        try:
            stale = window.session.status()
            callbacks = []
            with patch.object(
                window, "_submit", side_effect=lambda work, done, fail: callbacks.append(done)
            ):
                window._poll_async()
            window._poll()
            window._pending_action = "import"
            callbacks[0](stale)
            assert window._pending_action == "import"
        finally:
            window._exit_gui()


def test_window_close_hides_to_tray_without_stopping_daemon(
    tmp_path: Path, qapp: QApplication
) -> None:
    from PySide6.QtWidgets import QSystemTrayIcon

    from pdo.desktop.app import DesktopWindow

    config = _config(tmp_path)
    tray = MagicMock()
    with _running_daemon(config):
        with patch.object(DesktopWindow, "_create_tray", return_value=tray):
            window = DesktopWindow(DesktopSession(config, auto_start=False))
        window.show()
        qapp.processEvents()
        window.close()
        qapp.processEvents()
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


def test_tray_quit_stops_daemon_and_gui(tmp_path: Path, qapp: QApplication) -> None:
    from pdo.desktop.app import DesktopWindow

    config = _config(tmp_path)
    tray = MagicMock()
    tray.available = True
    with _running_daemon(config):
        with patch.object(DesktopWindow, "_create_tray", return_value=tray):
            window = DesktopWindow(DesktopSession(config, auto_start=False))
        window.show()
        qapp.processEvents()
        window.close()
        assert not window.isVisible()
        assert send_command("ping", config=config).success
        menu = window._build_qt_tray_menu()
        assert [action.text() for action in menu.actions()] == ["Open", "Quit"]
        menu.actions()[0].trigger()
        qapp.processEvents()
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


def test_tray_quit_keeps_gui_open_if_daemon_rejects_stop(
    tmp_path: Path, qapp: QApplication
) -> None:
    from pdo.desktop.app import DesktopWindow

    config = _config(tmp_path)
    tray = MagicMock()
    tray.available = True
    with _running_daemon(config):
        with patch.object(DesktopWindow, "_create_tray", return_value=tray):
            window = DesktopWindow(DesktopSession(config, auto_start=False))
        window.show()
        qapp.processEvents()
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


def test_window_close_quits_gui_when_tray_is_unavailable(
    tmp_path: Path, qapp: QApplication
) -> None:
    from pdo.desktop.app import DesktopWindow

    config = _config(tmp_path)
    with _running_daemon(config):
        with patch.object(DesktopWindow, "_create_tray", return_value=None):
            window = DesktopWindow(DesktopSession(config, auto_start=False))
        with patch.object(qapp, "quit") as quit_app:
            window.close()
        quit_app.assert_called_once()
        assert send_command("ping", config=config).success


def test_window_close_quits_gui_after_tray_host_disappears(
    tmp_path: Path, qapp: QApplication
) -> None:
    from pdo.desktop.app import DesktopWindow

    config = _config(tmp_path)
    tray = MagicMock()
    tray.available = False
    with _running_daemon(config):
        with patch.object(DesktopWindow, "_create_tray", return_value=tray):
            window = DesktopWindow(DesktopSession(config, auto_start=False))
        with patch.object(qapp, "quit") as quit_app:
            window.close()
        quit_app.assert_called_once()
        tray.stop.assert_called_once()
        assert send_command("ping", config=config).success


def test_openai_settings_discover_select_save_and_restore(
    tmp_path: Path, qapp: QApplication
) -> None:
    from pdo.core.provider_defaults import OPENAI_MODEL
    from pdo.desktop.app import DesktopWindow

    config = _config(tmp_path)
    with _running_daemon(config), patch.object(DesktopWindow, "_create_tray", return_value=None):
        window = DesktopWindow(DesktopSession(config, auto_start=False))
        try:
            window.show()
            window._open_settings()
            window.backend_box.setCurrentIndex(window.backend_box.findData("openai"))
            assert window.key_input.isVisible()
            assert window.connection_button.isVisible()
            assert window.model_box.isVisible()
            assert not window.address_input.isVisible()
            assert window._provider_settings()["openai.model"] == OPENAI_MODEL
            window.key_input.setText("new-key")
            with patch.object(
                window.session, "openai_models", return_value=["gpt-5-mini", "gpt-4.1"]
            ) as discover:
                window._check_connection()
                _process_until(qapp, lambda: window.model_box.count() == 2)
            discover.assert_called_once_with("new-key")
            window.model_box.setCurrentText("gpt-4.1")
            window._save_settings()
            saved = load_config(config_file=config.config_file_path)
            assert saved.optimizer == "openai"
            assert saved.options["openai.api_key"] == "new-key"
            assert saved.options["openai.model"] == "gpt-4.1"
            assert window._provider_settings()["openai.model"] == "gpt-4.1"
            window._open_settings()
            window.manual_model.setChecked(True)
            window.model_input.setText("future-model")
            assert window._provider_settings()["openai.model"] == "future-model"
            window._cancel_settings()
            assert window._provider_settings()["openai.model"] == "gpt-4.1"
            window.backend_box.setCurrentIndex(window.backend_box.findData("local_llm"))
            with pytest.raises(ValueError, match="Prüfe zuerst"):
                window._provider_settings()
        finally:
            window._exit_gui()


def test_openai_model_discovery_ignores_old_credentials_and_provider(
    qapp: QApplication, tmp_path: Path
) -> None:
    from pdo.desktop.app import DesktopWindow

    config = _config(tmp_path)
    with _running_daemon(config), patch.object(DesktopWindow, "_create_tray", return_value=None):
        window = DesktopWindow(DesktopSession(config, auto_start=False))
        try:
            window.backend_box.setCurrentIndex(window.backend_box.findData("openai"))
            with patch.object(window, "_submit") as submit:
                window._check_connection()
                old_finished = submit.call_args.args[1]
                window.key_input.setText("changed-key")
                old_finished(["stale-key-model"])
                assert window.model_box.findText("stale-key-model") == -1
                window._check_connection()
                old_finished = submit.call_args.args[1]
                window.backend_box.setCurrentIndex(window.backend_box.findData("gemini"))
                old_finished(["stale-provider-model"])
                assert window.model_box.findText("stale-provider-model") == -1
        finally:
            window._exit_gui()


def test_openai_subscription_keeps_api_and_subscription_models_separate(
    tmp_path: Path, qapp: QApplication
) -> None:
    from pdo.desktop.app import DesktopWindow

    config = _config(tmp_path)
    save_config_values(
        config.config_file_path,
        {"optimizer": "openai", "openai.api_key": "saved-key", "openai.model": "api-model"},
    )
    config = load_config(
        config_file=config.config_file_path,
        overrides={"data_dir": str(config.data_dir), "log_dir": str(config.log_dir)},
    )
    with _running_daemon(config), patch.object(DesktopWindow, "_create_tray", return_value=None):
        window = DesktopWindow(DesktopSession(config, auto_start=False))
        try:
            window.show()
            window._open_settings()
            window.openai_auth_box.setCurrentIndex(window.openai_auth_box.findData("chatgpt"))
            assert not window.key_input.isVisible()
            assert window.chatgpt_login_button.isVisible()
            assert window.model_box.count() == 0
            with pytest.raises(ValueError, match="ChatGPT"):
                window._provider_settings()
            with patch.object(
                window.session, "chatgpt_models", return_value=["codex-first", "codex-second"]
            ) as models:
                window.chatgpt_login_button.click()
                _process_until(qapp, lambda: window.model_box.count() == 2)
            models.assert_called_once_with(login=True)
            window.model_box.setCurrentText("codex-second")
            window._save_settings()
            assert window._provider_settings()["openai.chatgpt_model"] == "codex-second"
            saved = load_config(config_file=config.config_file_path)
            assert saved.options["openai.auth_mode"] == "chatgpt"
            assert saved.options["openai.api_key"] == "saved-key"
            assert saved.options["openai.model"] == "api-model"
            assert saved.options["openai.chatgpt_model"] == "codex-second"
            window._open_settings()
            window.openai_auth_box.setCurrentIndex(window.openai_auth_box.findData("api_key"))
            assert window._provider_settings()["openai.model"] == "api-model"
            window._cancel_settings()
            assert window.openai_auth_box.currentData() == "chatgpt"
            assert window._provider_settings()["openai.chatgpt_model"] == "codex-second"
        finally:
            window._exit_gui()


@pytest.mark.parametrize("finished_before_cancel", [False, True])
def test_cancel_openai_settings_restores_model_after_discovery(
    tmp_path: Path, qapp: QApplication, finished_before_cancel: bool
) -> None:
    from pdo.desktop.app import DesktopWindow

    config = _config(tmp_path)
    save_config_values(
        config.config_file_path,
        {"optimizer": "openai", "openai.api_key": "test", "openai.model": "saved-model"},
    )
    config = load_config(
        config_file=config.config_file_path,
        overrides={"data_dir": str(config.data_dir), "log_dir": str(config.log_dir)},
    )
    with _running_daemon(config), patch.object(DesktopWindow, "_create_tray", return_value=None):
        window = DesktopWindow(DesktopSession(config, auto_start=False))
        try:
            window._open_settings()
            with patch.object(window, "_submit") as submit:
                window._check_connection()
                finished = submit.call_args.args[1]
                if finished_before_cancel:
                    finished(["unsaved-model"])
                window._cancel_settings()
                if not finished_before_cancel:
                    finished(["unsaved-model"])
            assert window._provider_settings()["openai.model"] == "saved-model"
            assert window.connection_button.isEnabled()
            assert (
                load_config(config_file=config.config_file_path).options["openai.model"]
                == "saved-model"
            )
        finally:
            window._exit_gui()
