"""PySide6 desktop interface for the product description workflow."""

from __future__ import annotations

import logging
import sys
import tempfile
from importlib.resources import files
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QAction, QIcon, QImage
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pdo import __version__
from pdo.config import PdoConfig
from pdo.core.provider_defaults import (
    GEMINI_MODEL,
    LOCAL_LLM_ADDRESS,
    LOCAL_LLM_MODEL,
    ZHIPUAI_MODEL,
)
from pdo.desktop.session import CsvPreview, DesktopSession, inspect_csv, suggest_role
from pdo.exceptions import PdoError

log = logging.getLogger(__name__)

COLORS = {
    "canvas": "#0B1020",
    "sidebar": "#0F172A",
    "card": "#172239",
    "border": "#2A3853",
    "text": "#F3F6FC",
    "muted": "#A8B6CC",
    "accent": "#8B7CFF",
    "success": "#4ADEA6",
}

STYLESHEET = """
QMainWindow, QWidget#root, QScrollArea, QScrollArea > QWidget > QWidget {
    background: #0B1020; color: #F3F6FC;
}
QFrame#sidebar { background: #0F172A; border-right: 1px solid #2A3853; }
QFrame#card { background: #172239; border: 1px solid #2A3853; border-radius: 16px; }
QLabel { color: #F3F6FC; background: transparent; }
QLabel#muted { color: #A8B6CC; }
QLabel#eyebrow { color: #9D91FF; font-size: 12px; font-weight: 700; }
QLabel#headline { font-size: 26px; font-weight: 700; }
QLabel#stat { font-size: 26px; font-weight: 700; }
QPushButton {
    background: #263551; color: #F3F6FC; border: 1px solid #3B4D6A;
    border-radius: 10px; padding: 10px 16px; font-weight: 600;
}
QPushButton:hover { background: #344866; }
QPushButton:disabled { color: #8190A6; background: #1B263B; border-color: #293750; }
QPushButton#primary { background: #7567ED; color: white; border-color: #8B7CFF; }
QPushButton#primary:hover { background: #8B7CFF; }
QPushButton#nav { text-align: left; background: transparent; border: 0; padding: 12px 16px; }
QPushButton#nav:checked { background: #263455; color: #C7C0FF; }
QLineEdit, QComboBox, QPlainTextEdit {
    background: #111B2E; color: #F3F6FC; border: 1px solid #3B4D6A;
    border-radius: 9px; padding: 8px 10px; selection-background-color: #7567ED;
}
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus { border-color: #8B7CFF; }
QComboBox QAbstractItemView {
    background: #172239; color: #F3F6FC; selection-background-color: #344866;
}
QCheckBox { color: #F3F6FC; spacing: 10px; }
QTableWidget {
    background: #111B2E; alternate-background-color: #15213A; color: #F3F6FC;
    gridline-color: #2A3853; border: 1px solid #2A3853; border-radius: 10px;
    selection-background-color: #344866; selection-color: white;
}
QHeaderView::section {
    background: #1D2A43; color: #A8B6CC; border: 0; padding: 9px; font-weight: 600;
}
QProgressBar {
    background: #172239; border: 1px solid #2A3853; border-radius: 7px;
    height: 12px; text-align: center;
}
QProgressBar::chunk { background: #8B7CFF; border-radius: 6px; }
QScrollBar:vertical { background: #0B1020; width: 10px; }
QScrollBar::handle:vertical { background: #344866; border-radius: 5px; min-height: 24px; }
"""


def _label(text: str, kind: str | None = None) -> QLabel:
    label = QLabel(text)
    if kind:
        label.setObjectName(kind)
    label.setWordWrap(True)
    return label


def _card() -> tuple[QFrame, QVBoxLayout]:
    card = QFrame()
    card.setObjectName("card")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(20, 20, 20, 20)
    layout.setSpacing(12)
    return card, layout


def _table(headers: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setAlternatingRowColors(True)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setStretchLastSection(True)
    table.setMinimumHeight(190)
    return table


class _UiDispatcher(QObject):
    """Queue D-Bus tray actions onto the Qt GUI thread."""

    invoke = Signal(object)

    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)
        self.invoke.connect(self._invoke)

    @Slot(object)
    def _invoke(self, callback: Any) -> None:
        callback()


class DesktopWindow(QMainWindow):
    """Main window with import, optimizer, results, and export views."""

    def __init__(self, session: DesktopSession | None = None) -> None:
        super().__init__()
        self.session = session or DesktopSession()
        self.preview: CsvPreview | None = None
        self._mapping_boxes: list[tuple[str, QComboBox]] = []
        self._shown_products: list[dict[str, Any]] = []
        self._last_progress: tuple[int, int, int, int] | None = None
        self._was_busy = False
        self._daemon_unreachable = False
        self._quitting = False
        self._hidden_to_tray = False
        self._tray_notice_shown = False
        self.setWindowTitle("PDO · Product Description Optimizer")
        self.setMinimumSize(1050, 720)
        self.resize(1240, 820)
        icon = QIcon(str(files("pdo.desktop").joinpath("logo.png")))
        self.setWindowIcon(icon)
        self._tray_dispatcher = _UiDispatcher(self)
        self._tray = self._create_tray(icon)

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_sidebar())

        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_overview())
        self.pages.addWidget(self._build_import())
        self.pages.addWidget(self._build_optimizer())
        self.pages.addWidget(self._build_export())
        outer.addWidget(self.pages, 1)
        self._show_page(0)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._poll)
        self.timer.start(700)
        self._poll()

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(238)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(18, 30, 18, 22)
        layout.setSpacing(8)
        layout.addWidget(_label("PDO", "headline"))
        layout.addWidget(_label("Product Description Optimizer", "muted"))
        layout.addSpacing(30)
        self.nav_buttons: list[QPushButton] = []
        for index, text in enumerate(("Overview", "Import CSV", "Optimize", "Export")):
            button = QPushButton(text)
            button.setObjectName("nav")
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, page=index: self._show_page(page))
            layout.addWidget(button)
            self.nav_buttons.append(button)
        layout.addStretch(1)
        self.daemon_label = _label("Connecting to daemon…", "muted")
        layout.addWidget(self.daemon_label)
        return sidebar

    def _create_tray(self, icon: QIcon) -> Any | None:
        """Use direct StatusNotifier D-Bus on Linux and Qt tray elsewhere."""
        if sys.platform == "linux":
            try:
                from pdo.desktop.linux_tray import LinuxTrayController, icon_pixmap_from_rgba

                image = icon.pixmap(64, 64).toImage().convertToFormat(QImage.Format.Format_RGBA8888)
                rgba = bytes(image.bits()[: image.sizeInBytes()])
                pixmap = icon_pixmap_from_rgba(image.width(), image.height(), rgba)
                tray = LinuxTrayController(
                    pixmap,
                    self._tray_dispatcher.invoke.emit,
                    self._show_from_tray,
                    self.quit,
                )
                if tray.start():
                    return tray
                tray.stop()
            except Exception:
                log.exception("Could not start Linux StatusNotifier tray")
            return None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return None
        tray = QSystemTrayIcon(icon, self)
        tray.setToolTip("PDO · Product Description Optimizer")
        tray.setContextMenu(self._build_qt_tray_menu())
        tray.activated.connect(self._tray_activated)
        tray.show()
        return tray

    def _build_qt_tray_menu(self) -> QMenu:
        """Build the native tray menu used outside Linux."""
        menu = QMenu(self)
        open_action = QAction("Open", self)
        open_action.triggered.connect(self._show_from_tray)
        menu.addAction(open_action)
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self.quit)
        menu.addAction(quit_action)
        return menu

    def _tray_available(self) -> bool:
        """Only hide the window when an actual tray host is available."""
        if self._tray is None:
            return False
        if isinstance(self._tray, QSystemTrayIcon):
            return QSystemTrayIcon.isSystemTrayAvailable() and self._tray.isVisible()
        return bool(self._tray.available)

    def _show_from_tray(self) -> None:
        """Restore and focus the main window from the tray."""
        self._hidden_to_tray = False
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """Restore the window when the tray icon is clicked."""
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._show_from_tray()

    def _exit_gui(self) -> None:
        """Close this GUI client without changing daemon state."""
        self._quitting = True
        self.close()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def quit(self) -> None:
        """Stop the daemon and close the GUI from the tray exit action."""
        try:
            self.session.stop_daemon()
        except Exception as exc:
            self._show_from_tray()
            self._error(f"Could not stop the daemon: {exc}")
            return
        self._exit_gui()

    def _page(self, eyebrow: str, heading: str, subtitle: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(34, 30, 34, 28)
        layout.setSpacing(18)
        layout.addWidget(_label(eyebrow.upper(), "eyebrow"))
        layout.addWidget(_label(heading, "headline"))
        layout.addWidget(_label(subtitle, "muted"))
        return page, layout

    def _build_overview(self) -> QWidget:
        page, layout = self._page(
            "Workspace",
            "Your product descriptions at a glance",
            "Import a CSV, map its columns, improve descriptions, and export the results.",
        )
        stats = QHBoxLayout()
        self.stat_labels: dict[str, QLabel] = {}
        for key, title in (
            ("total", "Products"),
            ("pending", "Pending"),
            ("done", "Done"),
            ("error", "Errors"),
        ):
            card, card_layout = _card()
            card_layout.addWidget(_label(title, "muted"))
            value = _label("0", "stat")
            card_layout.addWidget(value)
            self.stat_labels[key] = value
            stats.addWidget(card)
        layout.addLayout(stats)

        progress_card, progress_layout = _card()
        progress_layout.addWidget(_label("Progress", "eyebrow"))
        self.stage_label = _label("Ready", "muted")
        progress_layout.addWidget(self.stage_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        progress_layout.addWidget(self.progress_bar)
        actions = QHBoxLayout()
        for text, page_index in (("Open CSV", 1), ("Choose optimizer", 2), ("Export", 3)):
            button = QPushButton(text)
            if page_index == 1:
                button.setObjectName("primary")
            button.clicked.connect(lambda checked=False, page=page_index: self._show_page(page))
            actions.addWidget(button)
        actions.addStretch(1)
        progress_layout.addLayout(actions)
        layout.addWidget(progress_card)

        results_card, results_layout = _card()
        results_layout.addWidget(_label("Products · first 100 entries", "eyebrow"))
        self.results_table = _table(["ID", "Status", "Original", "Optimized"])
        self.results_table.setColumnWidth(0, 125)
        self.results_table.setColumnWidth(1, 95)
        self.results_table.setColumnWidth(2, 310)
        self.results_table.itemSelectionChanged.connect(self._show_selected_product)
        results_layout.addWidget(self.results_table)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setPlaceholderText("Select a product to view the full text.")
        self.detail.setMaximumHeight(130)
        results_layout.addWidget(self.detail)
        layout.addWidget(results_card, 1)
        return page

    def _build_import(self) -> QWidget:
        page, layout = self._page(
            "Step 1",
            "Import CSV",
            "Choose a file and map its product ID, description, and context columns.",
        )
        file_card, file_layout = _card()
        file_layout.addWidget(_label("Source file", "eyebrow"))
        file_row = QHBoxLayout()
        self.file_path = QLineEdit()
        self.file_path.setPlaceholderText("No CSV file selected")
        self.file_path.setReadOnly(True)
        file_row.addWidget(self.file_path, 1)
        browse = QPushButton("Choose file")
        browse.clicked.connect(self._choose_source)
        file_row.addWidget(browse)
        file_layout.addLayout(file_row)
        self.format_label = _label("UTF-8 and CP1252 · delimiter detected automatically", "muted")
        file_layout.addWidget(self.format_label)
        layout.addWidget(file_card)

        map_card, map_layout = _card()
        map_layout.addWidget(_label("Column mapping", "eyebrow"))
        map_layout.addWidget(_label("Mark at least one column as Description.", "muted"))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setMaximumHeight(205)
        self.mapping_widget = QWidget()
        self.mapping_layout = QVBoxLayout(self.mapping_widget)
        self.mapping_layout.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(self.mapping_widget)
        map_layout.addWidget(scroll)
        layout.addWidget(map_card)

        sample_card, sample_layout = _card()
        sample_layout.addWidget(_label("File preview", "eyebrow"))
        self.sample_table = _table([])
        sample_layout.addWidget(self.sample_table)
        layout.addWidget(sample_card, 1)

        self.import_button = QPushButton("Import products")
        self.import_button.setObjectName("primary")
        self.import_button.clicked.connect(self._start_import)
        layout.addWidget(self.import_button, alignment=Qt.AlignmentFlag.AlignRight)
        return page

    def _build_optimizer(self) -> QWidget:
        page, layout = self._page(
            "Step 2",
            "Optimize descriptions",
            "Choose an AI provider and start processing. Progress is saved locally.",
        )
        config_card, config_layout = _card()
        config_layout.addWidget(_label("Provider & settings", "eyebrow"))
        form = QFormLayout()
        form.setSpacing(14)
        self.backend_box = QComboBox()
        for text, value in (
            ("Local AI server", "local_llm"),
            ("Google Gemini", "gemini"),
            ("ZhipuAI", "zhipuai"),
            ("Demo · uppercase text", "dummy"),
        ):
            self.backend_box.addItem(text, value)
        self.backend_box.currentIndexChanged.connect(self._backend_changed)
        form.addRow("Optimizer", self.backend_box)
        self.key_input = QLineEdit()
        self.key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_input.setPlaceholderText("API key")
        form.addRow("API key", self.key_input)
        self.model_input = QLineEdit()
        form.addRow("Model", self.model_input)
        self.address_input = QLineEdit()
        self.address_input.setPlaceholderText("http://127.0.0.1:11434/v1")
        form.addRow("Server address", self.address_input)
        self.style_input = QPlainTextEdit()
        self.style_input.setMaximumHeight(90)
        self.style_input.setPlaceholderText("Optional: tone, audience, or preferred style")
        form.addRow("Style instructions", self.style_input)
        config_layout.addLayout(form)
        config_layout.addWidget(_label("Settings are saved in ~/.pdo/config.toml.", "muted"))
        self.data_flow_label = _label("", "muted")
        config_layout.addWidget(self.data_flow_label)
        layout.addWidget(config_card)

        run_card, run_layout = _card()
        run_layout.addWidget(_label("Processing", "eyebrow"))
        self.run_status = _label("Ready", "muted")
        run_layout.addWidget(self.run_status)
        buttons = QHBoxLayout()
        self.optimize_button = QPushButton("Start optimization")
        self.optimize_button.setObjectName("primary")
        self.optimize_button.clicked.connect(self._start_optimization)
        buttons.addWidget(self.optimize_button)
        self.pause_button = QPushButton("Pause")
        self.pause_button.clicked.connect(self.session.pause)
        buttons.addWidget(self.pause_button)
        self.resume_button = QPushButton("Resume")
        self.resume_button.clicked.connect(self.session.resume)
        buttons.addWidget(self.resume_button)
        buttons.addStretch(1)
        run_layout.addLayout(buttons)
        layout.addWidget(run_card)
        layout.addStretch(1)
        backend = self.session.config.optimizer
        index = self.backend_box.findData(backend)
        self.backend_box.setCurrentIndex(index if index >= 0 else 0)
        self._backend_changed()
        return page

    def _build_export(self) -> QWidget:
        page, layout = self._page(
            "Step 3",
            "Export results",
            "Save completed descriptions with all original CSV columns in a new file.",
        )
        card, card_layout = _card()
        card_layout.addWidget(_label("Output file", "eyebrow"))
        row = QHBoxLayout()
        self.output_path = QLineEdit()
        self.output_path.setPlaceholderText("Choose an output file")
        row.addWidget(self.output_path, 1)
        choose = QPushButton("Choose location")
        choose.clicked.connect(self._choose_output)
        row.addWidget(choose)
        card_layout.addLayout(row)
        self.include_errors = QCheckBox("Include failed rows")
        card_layout.addWidget(self.include_errors)
        self.export_button = QPushButton("Export CSV")
        self.export_button.setObjectName("primary")
        self.export_button.clicked.connect(self._start_export)
        card_layout.addWidget(self.export_button, alignment=Qt.AlignmentFlag.AlignRight)
        layout.addWidget(card)
        layout.addStretch(1)
        return page

    def _show_page(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        for position, button in enumerate(self.nav_buttons):
            button.setChecked(position == index)

    def _choose_source(self) -> None:
        name, _ = QFileDialog.getOpenFileName(
            self, "Open CSV file", "", "CSV files (*.csv);;All files (*)"
        )
        if not name:
            return
        try:
            self.preview = inspect_csv(Path(name))
        except Exception as exc:
            self._error(str(exc))
            return
        self.file_path.setText(name)
        self.format_label.setText(
            f"{self.preview.encoding.upper()} · delimiter: {self.preview.delimiter!r} · "
            f"{len(self.preview.headers)} columns"
        )
        self._populate_mapping(self.preview)
        self._populate_sample(self.preview)
        self._poll()

    def _populate_mapping(self, preview: CsvPreview) -> None:
        while self.mapping_layout.count():
            item = self.mapping_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._mapping_boxes = []
        for header in preview.headers:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 2, 0, 2)
            name = _label(header)
            name.setMinimumWidth(220)
            row_layout.addWidget(name, 1)
            combo = QComboBox()
            for label, role in (
                ("Ignore", "ignore"),
                ("Product ID", "product_id"),
                ("Description", "description"),
                ("Context", "context"),
            ):
                combo.addItem(label, role)
            combo.setCurrentIndex(combo.findData(suggest_role(header)))
            combo.setMinimumWidth(180)
            row_layout.addWidget(combo)
            self.mapping_layout.addWidget(row)
            self._mapping_boxes.append((header, combo))
        self.mapping_layout.addStretch(1)

    def _populate_sample(self, preview: CsvPreview) -> None:
        table = self.sample_table
        table.setColumnCount(len(preview.headers))
        table.setHorizontalHeaderLabels(preview.headers)
        table.setRowCount(len(preview.rows))
        for row_number, values in enumerate(preview.rows):
            for column, value in enumerate(values[: len(preview.headers)]):
                table.setItem(row_number, column, QTableWidgetItem(value))
        for column in range(len(preview.headers)):
            table.setColumnWidth(column, 180)

    def _start_import(self) -> None:
        if self.preview is None:
            self._error("Choose a CSV file first.")
            return
        if self.session.status()["progress"]["total"]:
            answer = QMessageBox.question(
                self,
                "Replace existing products",
                "This import will replace the current product list. Continue?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        mappings = [
            {"role": combo.currentData(), "csv_column_name": header, "display_name": header}
            for header, combo in self._mapping_boxes
            if combo.currentData() != "ignore"
        ]
        try:
            self.session.import_file(self.preview, mappings)
        except Exception as exc:
            self._error(str(exc))
            return
        self._was_busy = True
        self._show_page(0)
        self._poll()

    def _backend_changed(self, _: int = 0) -> None:
        backend = self.backend_box.currentData()
        options = self.session.config.options
        remote = backend in ("gemini", "zhipuai")
        local = backend == "local_llm"
        self.key_input.setEnabled(remote)
        self.model_input.setEnabled(backend != "dummy")
        self.address_input.setEnabled(local)
        self.key_input.setText(options.get(f"{backend}.api_key", "") if remote else "")
        defaults = {
            "gemini": GEMINI_MODEL,
            "zhipuai": ZHIPUAI_MODEL,
            "local_llm": LOCAL_LLM_MODEL,
        }
        self.model_input.setText(options.get(f"{backend}.model", defaults.get(backend, "")))
        self.address_input.setText(options.get("local_llm.address", LOCAL_LLM_ADDRESS))
        self.style_input.setPlainText(options.get("style_instructions", ""))
        if remote:
            self.data_flow_label.setText(
                "Descriptions and selected context fields are sent to the chosen "
                "cloud provider for processing."
            )
        elif local:
            self.data_flow_label.setText(
                "Descriptions and context fields are sent to the configured server address."
            )
        else:
            self.data_flow_label.setText("Demo mode processes descriptions on this computer.")

    def _start_optimization(self) -> None:
        backend = self.backend_box.currentData()
        settings = {"style_instructions": self.style_input.toPlainText().strip()}
        if backend in ("gemini", "zhipuai"):
            settings[f"{backend}.api_key"] = self.key_input.text().strip()
            settings[f"{backend}.model"] = self.model_input.text().strip()
        elif backend == "local_llm":
            settings["local_llm.address"] = self.address_input.text().strip()
            settings["local_llm.model"] = self.model_input.text().strip()
        try:
            self.session.optimize(backend, settings)
        except Exception as exc:
            self._error(str(exc))
            return
        self._was_busy = True
        self._poll()

    def _choose_output(self) -> None:
        name, _ = QFileDialog.getSaveFileName(
            self, "Export CSV", "optimized-products.csv", "CSV files (*.csv)"
        )
        if name:
            self.output_path.setText(name)

    def _start_export(self) -> None:
        name = self.output_path.text().strip()
        if not name:
            self._error("Choose where to save the CSV file.")
            return
        try:
            self.session.export_file(Path(name), include_errors=self.include_errors.isChecked())
        except Exception as exc:
            self._error(str(exc))
            return
        self._was_busy = True
        self._poll()

    def _poll(self) -> None:
        if self._hidden_to_tray and not self._tray_available():
            self._show_from_tray()
        try:
            status = self.session.status()
        except (PdoError, RuntimeError) as exc:
            self._daemon_unreachable = True
            self.daemon_label.setText("Daemon unavailable")
            self.run_status.setText("Daemon unavailable")
            self.statusBar().showMessage(f"Daemon unavailable: {exc}")
            return
        self.daemon_label.setText(f"Daemon running · v{__version__}")
        if self._daemon_unreachable:
            self._daemon_unreachable = False
            self.statusBar().clearMessage()
        progress = status["progress"]
        busy = status["busy"]
        for key, label in self.stat_labels.items():
            label.setText(str(progress[key]))
        total = progress["total"]
        completed = progress["done"] + progress["error"]
        self.progress_bar.setValue(round(100 * completed / total) if total else 0)
        stage_names = {
            "idle": "Ready",
            "importing": "Importing CSV",
            "optimizing": "Optimizing",
            "exporting": "Exporting CSV",
        }
        state_text = stage_names.get(status["stage"], status["stage"])
        if status["paused"]:
            state_text = "Paused · finishing current product"
        self.stage_label.setText(f"{state_text} · {completed} of {total} processed")
        self.run_status.setText(state_text)
        self.import_button.setEnabled(self.preview is not None and not busy)
        self.optimize_button.setEnabled(progress["pending"] > 0 and not busy)
        self.export_button.setEnabled(
            not busy
            and (
                progress["done"] > 0 or (self.include_errors.isChecked() and progress["error"] > 0)
            )
        )
        self.pause_button.setEnabled(
            busy and status["stage"] == "optimizing" and not status["paused"]
        )
        self.resume_button.setEnabled(busy and status["paused"])
        progress_key = (total, progress["pending"], progress["done"], progress["error"])
        if progress_key != self._last_progress:
            self._last_progress = progress_key
            self._refresh_products()
        if self._was_busy and not busy:
            result = status["last_result"]
            if result.get("error"):
                self._error(result["error"])
            elif result.get("errors"):
                errors = result["errors"]
                error_count = result.get("error_count", len(errors))
                preview = "\n".join(str(error) for error in errors[:3])
                suffix = f"\n… and {error_count - 3} more" if error_count > 3 else ""
                self._error(
                    f"Import finished, but {error_count} rows were skipped.\n{preview}{suffix}"
                )
            elif result:
                self.statusBar().showMessage("Operation completed.", 7000)
            self._refresh_products()
        self._was_busy = busy

    def _refresh_products(self) -> None:
        self._shown_products = self.session.products()
        table = self.results_table
        selected = table.currentRow()
        table.setRowCount(len(self._shown_products))
        for row_number, product in enumerate(self._shown_products):
            values = (
                product["product_id_value"],
                product["status"],
                product["original_description"],
                product["optimized_description"] or "",
            )
            for column, value in enumerate(values):
                table.setItem(row_number, column, QTableWidgetItem(str(value)))
        if 0 <= selected < table.rowCount():
            table.selectRow(selected)

    def _show_selected_product(self) -> None:
        row = self.results_table.currentRow()
        if not 0 <= row < len(self._shown_products):
            return
        try:
            product = self.session.product(int(self._shown_products[row]["id"]))
        except Exception as exc:
            self._error(str(exc))
            return
        original_suffix = "\n[… truncated]" if product["original_truncated"] else ""
        optimized_suffix = "\n[… truncated]" if product["optimized_truncated"] else ""
        error_suffix = "\n[… truncated]" if product["error_truncated"] else ""
        self.detail.setPlainText(
            f"Original\n{product['original_description']}{original_suffix}\n\n"
            f"Optimized\n{product['optimized_description'] or '—'}{optimized_suffix}"
            + (
                f"\n\nError\n{product['error_message']}{error_suffix}"
                if product["error_message"]
                else ""
            )
        )

    def _error(self, message: str) -> None:
        QMessageBox.warning(self, "PDO", message)

    def closeEvent(self, event: Any) -> None:  # noqa: N802 - Qt override
        """Hide in the tray or close only this GUI client."""
        if not self._quitting and self._tray_available():
            self._hidden_to_tray = True
            self.hide()
            event.ignore()
            if not self._tray_notice_shown:
                message = "PDO is in the system tray. The daemon continues running."
                if isinstance(self._tray, QSystemTrayIcon):
                    self._tray.showMessage(
                        "PDO is running",
                        message,
                        QSystemTrayIcon.MessageIcon.Information,
                        4000,
                    )
                else:
                    self._tray.notify(message)
                self._tray_notice_shown = True
            return
        self.timer.stop()
        self.session.close()
        if self._tray is not None:
            if isinstance(self._tray, QSystemTrayIcon):
                self._tray.hide()
            else:
                self._tray.stop()
        event.accept()
        if not self._tray_available():
            app = QApplication.instance()
            if app is not None:
                app.quit()


def main() -> int:
    """Launch the desktop application or run the packaged smoke check."""
    if "--daemon-process" in sys.argv:
        from pdo.daemon.entry import main as daemon_main

        return daemon_main(sys.argv[1:])
    if "--smoke-test" in sys.argv:
        from google import genai
        from openai import OpenAI
        from zhipuai import ZhipuAI

        from pdo.core.registry import list_optimizers

        if sys.platform == "linux":
            from pdo.desktop.linux_tray import StatusNotifierItem

            assert StatusNotifierItem

        assert list_optimizers()
        assert genai.Client(api_key="package-smoke-test").models
        assert OpenAI(base_url="http://127.0.0.1:1/v1", api_key="package-smoke-test").chat
        assert ZhipuAI(api_key="package-smoke-test.package-smoke-test").chat
        app = QApplication(["pdo-smoke-test"])
        with tempfile.TemporaryDirectory(prefix="pdo-smoke-") as temp_dir:
            base = Path(temp_dir)
            session = DesktopSession(
                PdoConfig(
                    data_dir=base / "data",
                    log_dir=base / "logs",
                    socket_path=base / "pdo.sock",
                    config_file_path=base / "config.toml",
                )
            )
            window = DesktopWindow(session)
            from pdo.daemon.pid import read_pid, wait_for_exit

            daemon_pid = read_pid(session.config.data_dir / "daemon.pid")
            assert daemon_pid is not None
            window.quit()
            from pdo.daemon.endpoint import endpoint_file

            assert wait_for_exit(daemon_pid, 5.0)
            assert not endpoint_file(session.config).exists()
        app.quit()
        return 0
    app = QApplication(sys.argv)
    app.setApplicationName("PDO")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)
    try:
        window = DesktopWindow()
    except Exception as exc:
        QMessageBox.critical(None, "PDO could not start", str(exc))
        return 1
    app.setQuitOnLastWindowClosed(not window._tray_available())
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
