from __future__ import annotations

__doc__ = "Exercise the desktop through mouse/key events, real dialogs, and a real daemon."

import csv
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialogButtonBox,
    QFileDialog,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QWidget,
)

from pdo.config import load_config, save_config_values
from pdo.core.db import Database
from pdo.core.optimizer import DummyOptimizer
from pdo.desktop.app import DesktopWindow
from pdo.desktop.session import DesktopSession
from test_desktop import _config, _running_daemon


def wait_for(condition: Callable[[], bool], timeout: float = 15) -> None:
    """Pump Qt events while waiting for asynchronous UI state."""
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
    assert condition(), "GUI did not reach the expected state"


def click(widget: QWidget) -> None:
    """Click an enabled control only if its center is actually visible."""
    QApplication.processEvents()
    assert widget.isEnabled(), f"Disabled control: {widget.objectName()}"
    assert widget.isVisible(), f"Hidden control: {widget.objectName()}"
    assert widget.visibleRegion().contains(widget.rect().center()), "Control is clipped"
    point = (
        QPoint(8, widget.height() // 2) if isinstance(widget, QCheckBox) else widget.rect().center()
    )
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton, pos=point)
    QApplication.processEvents()


def named(window: DesktopWindow, text: str) -> QPushButton:
    """Find a visible button by the label a user sees."""
    return next(w for w in window.findChildren(QPushButton) if w.text() == text and w.isVisible())


def choose_file(action: QWidget, path: Path | None) -> None:
    """Operate the actual Qt file dialog through bounded mouse/key events."""
    handled = []
    failures = []
    deadline = time.monotonic() + 5
    timer = QTimer()

    def respond() -> None:
        dialog = QApplication.activeModalWidget()
        if time.monotonic() >= deadline:
            failures.append(f"File dialog did not finish for {path!s}")
            timer.stop()
            if dialog is not None:
                dialog.close()
            return
        if not isinstance(dialog, QFileDialog):
            return
        if path is None:
            handled.append(True)
            QTest.keyClick(dialog, Qt.Key.Key_Escape)
        elif not handled:
            handled.append(True)
            field = dialog.findChild(QLineEdit, "fileNameEdit")
            if field is None:
                failures.append("File dialog has no filename input")
                timer.stop()
                dialog.reject()
                return
            field.setFocus()
            QTest.keyClick(field, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
            QTest.keyClicks(field, str(path))
        else:
            # Let Qt's filename completion settle before clicking Open/Save.
            # An immediate Return can be consumed without accepting the dialog.
            box = dialog.findChild(QDialogButtonBox)
            if box is not None:
                for item in box.buttons():
                    if box.buttonRole(item) == QDialogButtonBox.ButtonRole.AcceptRole:
                        if item.isEnabled():
                            QTest.mouseClick(item, Qt.MouseButton.LeftButton)
                        break

    timer.timeout.connect(respond)
    timer.start(20)
    try:
        click(action)
    finally:
        timer.stop()
    assert not failures, failures
    assert handled, "File dialog was not opened"


def capture(window: DesktopWindow, name: str) -> None:
    """Optionally retain real window screenshots for visual review."""
    original = window.size()
    for width, height in ((960, 700), (1120, 850), (1440, 1000)):
        window.resize(width, height)
        QApplication.processEvents()
        # Test the window's actual footer controls, not just their logical visibility.
        frame = window.pages.currentWidget()
        row = frame.layout().itemAt(1)
        if row and row.layout():
            for index in range(row.layout().count()):
                widget = row.layout().itemAt(index).widget()
                if widget and widget.isVisible():
                    assert widget.visibleRegion().contains(widget.rect()), (
                        name,
                        widget.text(),
                        width,
                    )
        if directory := os.environ.get("PDO_UI_ARTIFACT_DIR"):
            path = Path(directory)
            path.mkdir(parents=True, exist_ok=True)
            assert window.grab().save(str(path / f"{name}-{width}x{height}.png"))
    window.resize(original)
    QApplication.processEvents()


def test_cancel_settings_keeps_text_draft_and_discards_provider_changes(
    tmp_path: Path, qapp: QApplication
) -> None:
    config = _config(tmp_path)
    save_config_values(config.config_file_path, {"optimizer": "gemini", "gemini.api_key": "test"})
    config = load_config(
        config_file=config.config_file_path,
        overrides={
            "data_dir": str(config.data_dir),
            "log_dir": str(config.log_dir),
            "socket_path": str(config.socket_path),
        },
    )
    with _running_daemon(config), patch.object(DesktopWindow, "_create_tray", return_value=None):
        window = DesktopWindow(DesktopSession(config, auto_start=False))
        try:
            window.show()
            # Populate through the text editor; cancelling connection settings must not erase it.
            window.style_input.setPlainText("Factual, friendly, and conversational.")
            click(window.settings_button)
            window.backend_box.setCurrentIndex(window.backend_box.findData("dummy"))
            click(named(window, "Cancel"))
            assert window.backend_box.currentData() == "gemini"
            assert window.style_input.toPlainText() == "Factual, friendly, and conversational."
            click(window.settings_button)
            window.backend_box.setCurrentIndex(window.backend_box.findData("dummy"))
            click(window.nav_buttons[0])
            assert window.backend_box.currentData() == "gemini"
        finally:
            window._exit_gui()


class ControlledOptimizer(DummyOptimizer):
    """Generate predictable failures while exercising the real worker and DB."""

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.attempts: dict[str, int] = {}

    def optimize(
        self, product_id: str, description: str, context: dict[str, str] | None = None
    ) -> str:
        self.attempts[product_id] = self.attempts.get(product_id, 0) + 1
        if not self.started.is_set():
            self.started.set()
            assert self.release.wait(20)
        number = int(product_id[1:])
        if 19_641 <= number <= 19_978 and self.attempts[product_id] == 1:
            raise TimeoutError("Request timed out")
        return super().optimize(product_id, description, context)


def test_twenty_thousand_product_flow_by_clicks_and_actual_files(
    tmp_path: Path, qapp: QApplication
) -> None:
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs, True)
    qapp.setStyle("Fusion")
    config = _config(tmp_path)
    source = tmp_path / "catalog.csv"
    with source.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, delimiter=";")
        writer.writerow(["SKU", "Description"])
        writer.writerows(
            (f"P{i:05}", f'Bag size L, "blue" {i}' if i <= 19978 else "") for i in range(1, 20_001)
        )
    optimizer = ControlledOptimizer()
    with (
        _running_daemon(config),
        patch.object(DesktopWindow, "_create_tray", return_value=None),
        patch("pdo.daemon.worker.create_optimizer", return_value=optimizer),
        patch("pdo.desktop.app.QMessageBox.warning") as warning,
    ):
        window = DesktopWindow(DesktopSession(config, auto_start=False))
        try:
            window.show()
            capture(window, "01-import-leer")
            choose_file(window.browse_button, None)
            assert window.preview is None
            choose_file(window.browse_button, source)
            assert window.sample_table.rowCount() == 2
            capture(window, "02-column-mapping")
            click(window.import_button)
            wait_for(lambda: window.pages.currentIndex() == 1)
            click(window.settings_button)
            window.backend_box.setCurrentIndex(window.backend_box.findData("dummy"))
            click(window.settings_save_button)
            capture(window, "03-optimization")
            click(window.optimize_button)
            wait_for(lambda: optimizer.started.is_set() and window.pause_button.isVisible())
            capture(window, "04-processing")
            click(window.pause_button)
            optimizer.release.set()
            wait_for(lambda: window._status.get("paused") is True)
            QTest.qWait(100)
            capture(window, "04-paused")
            before = len(optimizer.attempts)
            QTest.qWait(150)
            assert len(optimizer.attempts) == before
            # Close and reopen the actual client while the daemon retains the paused job.
            window._exit_gui()
            window = DesktopWindow(DesktopSession(config, auto_start=False))
            window.show()
            assert window.pause_button.text() == "Resume"
            click(window.pause_button)
            wait_for(lambda: window.pages.currentIndex() == 2, timeout=45)
            assert window._status["progress"] == {
                "total": 20_000,
                "done": 19_640,
                "error": 360,
                "pending": 0,
                "processing": 0,
            }
            capture(window, "05-error-groups")
            click(window.select_errors)
            assert not window.retry_button.isEnabled()
            click(window.select_errors)
            assert "338" in window.retry_button.text()
            click(window.retry_button)
            wait_for(
                lambda: (
                    window.pages.currentIndex() == 2 and window._status["progress"]["error"] == 22
                )
            )
            assert optimizer.attempts["P00001"] == 1
            assert optimizer.attempts["P19641"] == 2
            click(window.correction_export_button)
            wait_for(lambda: window.save_button.isEnabled())
            correction = tmp_path / "correction.csv"
            choose_file(window.save_button, correction)
            wait_for(lambda: "Saved:" in window.export_error.text())
            with correction.open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream, delimiter=";"))
            assert len(rows) == 22
            with correction.open("w", encoding="utf-16", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=["SKU", "Description"], delimiter=";")
                writer.writeheader()
                writer.writerows({**row, "Description": "Completed bag"} for row in rows)
            click(window.nav_buttons[2])
            choose_file(window.correction_import_button, correction)
            wait_for(lambda: window.retry_button.isEnabled())
            assert "22" in window.retry_button.text()
            click(window.retry_button)
            wait_for(
                lambda: (
                    window.pages.currentIndex() == 2
                    and window._status["progress"]["done"] == 20_000
                )
            )
            capture(window, "06-all-done")
            choose_file(window.new_button, None)
            assert window.pages.currentIndex() == 2
            bar = window.result_tabs.tabBar()
            QTest.mouseClick(bar, Qt.MouseButton.LeftButton, pos=bar.tabRect(0).center())
            click(window.next_button)
            assert window.results_table.item(0, 0).text() == "P00101"
            window.search_input.setFocus()
            QTest.keyClicks(window.search_input, "P20000")
            QTest.keyClick(window.search_input, Qt.Key.Key_Return)
            assert window.results_table.rowCount() == 1
            assert "COMPLETED BAG" in window.detail.toPlainText()
            capture(window, "06-textvergleich")
            click(window.export_button)
            wait_for(lambda: window.save_button.isEnabled())
            capture(window, "07-export-standard")
            click(window.format_editor.toggle)
            window.format_editor.encoding.setCurrentIndex(
                window.format_editor.encoding.findData("utf-16-le")
            )
            window.format_editor.delimiter.setCurrentIndex(
                window.format_editor.delimiter.findData("\t")
            )
            wait_for(lambda: window.save_button.isEnabled())
            capture(window, "08-export-utf16")
            output = tmp_path / "target-system.csv"
            choose_file(window.save_button, output)
            wait_for(lambda: "Saved:" in window.export_error.text())
            capture(window, "09-export-done")
            assert output.read_bytes().startswith(b"\xff\xfe")
            with output.open(encoding="utf-16", newline="") as stream:
                rows = list(csv.DictReader(stream, delimiter="\t"))
            assert len(rows) == 20_000
            assert rows[-1]["optimized_description"] == "[OPTIMIZED] COMPLETED BAG"
            click(window.prepare_export_button)
            click(window.format_editor.advanced_toggle)
            scroll = window.pages.currentWidget().findChild(QScrollArea)
            scroll.ensureWidgetVisible(window.format_editor.header)
            click(window.format_editor.header)
            wait_for(lambda: window.save_button.isEnabled())
            assert not window.export_preview.toPlainText().startswith("SKU")
            scroll.ensureWidgetVisible(window.format_editor.advanced)
            capture(window, "14-export-details")
            # Reach lower controls using the same scroll area a user operates.
            window.format_editor.delimiter.setCurrentIndex(5)
            scroll = window.pages.currentWidget().findChild(QScrollArea)
            scroll.ensureWidgetVisible(window.format_editor.custom)
            window.format_editor.custom.setFocus()
            QTest.keyClicks(window.format_editor.custom, "xx")
            wait_for(lambda: "one character" in window.export_error.text())
            assert not window.save_button.isEnabled()
            assert "valid CSV format" in window.export_preview.toPlainText()
            scroll.verticalScrollBar().setValue(0)
            capture(window, "15-export-ungueltig")
            assert warning.call_count == 0, warning.call_args_list
        finally:
            optimizer.release.set()
            window._exit_gui()


def test_model_discovery_through_local_http_and_real_controls(
    tmp_path: Path, qapp: QApplication
) -> None:
    import json
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    available = ["local-model"]
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            requests.append(self.path)
            payload = json.dumps({"data": [{"id": model} for model in available]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    config = _config(tmp_path)
    try:
        with (
            _running_daemon(config),
            patch.object(DesktopWindow, "_create_tray", return_value=None),
        ):
            window = DesktopWindow(DesktopSession(config, auto_start=False))
            try:
                window.show()
                click(window.settings_button)
                window.address_input.setFocus()
                QTest.keyClick(
                    window.address_input, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier
                )
                QTest.keyClicks(window.address_input, f"http://127.0.0.1:{server.server_port}/v1")
                click(window.connection_button)
                wait_for(lambda: window._models == ["local-model"])
                assert not window.model_box.isVisible()
                assert not window.model_input.isVisible()
                capture(window, "10-connection-one-model")
                available.append("second-model")
                click(window.connection_button)
                wait_for(lambda: window.model_box.isVisible())
                window.model_box.setFocus()
                QTest.keyClick(window.model_box, Qt.Key.Key_Down)
                assert window.model_box.currentText() == "second-model"
                capture(window, "11-connection-multiple-models")
                click(window.settings_save_button)
                assert window.session.config.options["local_llm.model"] == "second-model"
                source = tmp_path / "local-catalog.csv"
                source.write_text("SKU;Description\nP1;Blue bag\n", encoding="utf-8")
                choose_file(window.browse_button, source)
                click(window.import_button)
                wait_for(lambda: window.pages.currentIndex() == 1)
                assert window.style_input.isVisible()
                capture(window, "03-local-optimization")
                click(window.text_options_toggle)
                capture(window, "03-text-options")
                click(window.settings_button)
                window.backend_box.setFocus()
                QTest.keyClick(window.backend_box, Qt.Key.Key_Down)
                assert window.backend_box.currentData() == "gemini"
                assert window.key_input.isVisible()
                assert not window.model_input.isVisible()
                assert not window.address_input.isVisible()
                capture(window, "12-cloud-connection")
                click(window.manual_model)
                assert window.model_input.isVisible()
                capture(window, "13-manual-model")
                assert requests == ["/v1/models", "/v1/models"]
            finally:
                window._exit_gui()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_partial_error_group_selection_by_mouse(tmp_path: Path, qapp: QApplication) -> None:
    config = _config(tmp_path)
    config.data_dir.mkdir()
    with Database(config.data_dir / "pdo.db") as db:
        db.initialize()
        db.insert_products(
            [
                {
                    "source_row_number": i,
                    "product_id_value": f"P{i}",
                    "raw_data": {},
                    "original_description": "Bag",
                }
                for i in range(3)
            ]
        )
        db.update_product_status(1, "error", error_message="timeout")
        db.update_product_status(2, "error", error_message="connection refused")
        db.update_product_status(3, "error", error_message="missing", error_kind="missing_data")
    with _running_daemon(config), patch.object(DesktopWindow, "_create_tray", return_value=None):
        window = DesktopWindow(DesktopSession(config, auto_start=False))
        try:
            window.show()
            bar = window.result_tabs.tabBar()
            QTest.mouseClick(bar, Qt.MouseButton.LeftButton, pos=bar.tabRect(1).center())
            table = window.errors_table
            selected = next(
                table.item(i, 0)
                for i in range(table.rowCount())
                if table.item(i, 0).checkState() == Qt.CheckState.Checked
            )
            rect = table.visualItemRect(selected)
            QTest.mouseClick(
                table.viewport(),
                Qt.MouseButton.LeftButton,
                pos=QPoint(rect.left() + 8, rect.center().y()),
            )
            assert len(window._selected_groups()) == 1
            assert window.select_errors.checkState() == Qt.CheckState.PartiallyChecked
            click(window.select_errors)
            assert len(window._selected_groups()) == 2
            click(window.select_errors)
            assert window._selected_groups() == []
            assert not window.retry_button.isEnabled()
        finally:
            window._exit_gui()
