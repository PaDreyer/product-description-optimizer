"""PySide6 desktop interface for the product description workflow."""

from __future__ import annotations

import sys
import tempfile
from importlib.resources import files
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon
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
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStackedWidget,
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
        self.setWindowTitle("PDO · Product Description Optimizer")
        self.setMinimumSize(1050, 720)
        self.resize(1240, 820)
        icon = files("pdo.desktop").joinpath("logo.png")
        self.setWindowIcon(QIcon(str(icon)))

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
        for index, text in enumerate(("Übersicht", "CSV importieren", "Optimieren", "Exportieren")):
            button = QPushButton(text)
            button.setObjectName("nav")
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, page=index: self._show_page(page))
            layout.addWidget(button)
            self.nav_buttons.append(button)
        layout.addStretch(1)
        layout.addWidget(_label("Lokaler Arbeitsstand · Version " + __version__, "muted"))
        return sidebar

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
            "Arbeitsbereich",
            "Deine Produkttexte im Blick",
            "CSV laden, Spalten zuordnen, Texte verbessern und das Ergebnis exportieren.",
        )
        stats = QHBoxLayout()
        self.stat_labels: dict[str, QLabel] = {}
        for key, title in (
            ("total", "Produkte"),
            ("pending", "Offen"),
            ("done", "Fertig"),
            ("error", "Fehler"),
        ):
            card, card_layout = _card()
            card_layout.addWidget(_label(title, "muted"))
            value = _label("0", "stat")
            card_layout.addWidget(value)
            self.stat_labels[key] = value
            stats.addWidget(card)
        layout.addLayout(stats)

        progress_card, progress_layout = _card()
        progress_layout.addWidget(_label("Fortschritt", "eyebrow"))
        self.stage_label = _label("Bereit", "muted")
        progress_layout.addWidget(self.stage_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        progress_layout.addWidget(self.progress_bar)
        actions = QHBoxLayout()
        for text, page_index in (("CSV öffnen", 1), ("Optimierer wählen", 2), ("Export", 3)):
            button = QPushButton(text)
            if page_index == 1:
                button.setObjectName("primary")
            button.clicked.connect(lambda checked=False, page=page_index: self._show_page(page))
            actions.addWidget(button)
        actions.addStretch(1)
        progress_layout.addLayout(actions)
        layout.addWidget(progress_card)

        results_card, results_layout = _card()
        results_layout.addWidget(_label("Produkte · erste 100 Einträge", "eyebrow"))
        self.results_table = _table(["ID", "Status", "Original", "Optimiert"])
        self.results_table.setColumnWidth(0, 125)
        self.results_table.setColumnWidth(1, 95)
        self.results_table.setColumnWidth(2, 310)
        self.results_table.itemSelectionChanged.connect(self._show_selected_product)
        results_layout.addWidget(self.results_table)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setPlaceholderText("Produkt auswählen, um den vollständigen Text zu sehen.")
        self.detail.setMaximumHeight(130)
        results_layout.addWidget(self.detail)
        layout.addWidget(results_card, 1)
        return page

    def _build_import(self) -> QWidget:
        page, layout = self._page(
            "Schritt 1",
            "CSV importieren",
            "Datei auswählen und festlegen, welche Spalten ID, Beschreibung und Kontext enthalten.",
        )
        file_card, file_layout = _card()
        file_layout.addWidget(_label("Quelldatei", "eyebrow"))
        file_row = QHBoxLayout()
        self.file_path = QLineEdit()
        self.file_path.setPlaceholderText("Noch keine CSV-Datei ausgewählt")
        self.file_path.setReadOnly(True)
        file_row.addWidget(self.file_path, 1)
        browse = QPushButton("Datei wählen")
        browse.clicked.connect(self._choose_source)
        file_row.addWidget(browse)
        file_layout.addLayout(file_row)
        self.format_label = _label("UTF-8 und CP1252 · Trennzeichen werden erkannt", "muted")
        file_layout.addWidget(self.format_label)
        layout.addWidget(file_card)

        map_card, map_layout = _card()
        map_layout.addWidget(_label("Spaltenzuordnung", "eyebrow"))
        map_layout.addWidget(
            _label("Mindestens eine Spalte muss als Beschreibung markiert sein.", "muted")
        )
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
        sample_layout.addWidget(_label("Dateivorschau", "eyebrow"))
        self.sample_table = _table([])
        sample_layout.addWidget(self.sample_table)
        layout.addWidget(sample_card, 1)

        self.import_button = QPushButton("Produkte importieren")
        self.import_button.setObjectName("primary")
        self.import_button.clicked.connect(self._start_import)
        layout.addWidget(self.import_button, alignment=Qt.AlignmentFlag.AlignRight)
        return page

    def _build_optimizer(self) -> QWidget:
        page, layout = self._page(
            "Schritt 2",
            "Beschreibungen optimieren",
            "Einen Anbieter wählen und die Verarbeitung starten. "
            "Der Fortschritt wird lokal gespeichert.",
        )
        config_card, config_layout = _card()
        config_layout.addWidget(_label("Anbieter & Einstellungen", "eyebrow"))
        form = QFormLayout()
        form.setSpacing(14)
        self.backend_box = QComboBox()
        for text, value in (
            ("Lokaler LLM-Server", "local_llm"),
            ("Google Gemini", "gemini"),
            ("ZhipuAI", "zhipuai"),
            ("Demo · Text in Großbuchstaben", "dummy"),
        ):
            self.backend_box.addItem(text, value)
        self.backend_box.currentIndexChanged.connect(self._backend_changed)
        form.addRow("Optimierer", self.backend_box)
        self.key_input = QLineEdit()
        self.key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_input.setPlaceholderText("API-Schlüssel")
        form.addRow("API-Schlüssel", self.key_input)
        self.model_input = QLineEdit()
        form.addRow("Modell", self.model_input)
        self.address_input = QLineEdit()
        self.address_input.setPlaceholderText("http://127.0.0.1:11434/v1")
        form.addRow("Server-Adresse", self.address_input)
        self.style_input = QPlainTextEdit()
        self.style_input.setMaximumHeight(90)
        self.style_input.setPlaceholderText("Optional: Ton, Zielgruppe oder gewünschter Stil")
        form.addRow("Stilhinweise", self.style_input)
        config_layout.addLayout(form)
        config_layout.addWidget(
            _label("Einstellungen werden in ~/.pdo/config.toml gespeichert.", "muted")
        )
        self.data_flow_label = _label("", "muted")
        config_layout.addWidget(self.data_flow_label)
        layout.addWidget(config_card)

        run_card, run_layout = _card()
        run_layout.addWidget(_label("Verarbeitung", "eyebrow"))
        self.run_status = _label("Bereit", "muted")
        run_layout.addWidget(self.run_status)
        buttons = QHBoxLayout()
        self.optimize_button = QPushButton("Optimierung starten")
        self.optimize_button.setObjectName("primary")
        self.optimize_button.clicked.connect(self._start_optimization)
        buttons.addWidget(self.optimize_button)
        self.pause_button = QPushButton("Pausieren")
        self.pause_button.clicked.connect(self.session.pause)
        buttons.addWidget(self.pause_button)
        self.resume_button = QPushButton("Fortsetzen")
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
            "Schritt 3",
            "Ergebnis exportieren",
            "Fertige Beschreibungen mit allen ursprünglichen CSV-Spalten als neue Datei speichern.",
        )
        card, card_layout = _card()
        card_layout.addWidget(_label("Zieldatei", "eyebrow"))
        row = QHBoxLayout()
        self.output_path = QLineEdit()
        self.output_path.setPlaceholderText("Zieldatei auswählen")
        row.addWidget(self.output_path, 1)
        choose = QPushButton("Speicherort wählen")
        choose.clicked.connect(self._choose_output)
        row.addWidget(choose)
        card_layout.addLayout(row)
        self.include_errors = QCheckBox("Fehlerhafte Zeilen ebenfalls exportieren")
        card_layout.addWidget(self.include_errors)
        self.export_button = QPushButton("CSV exportieren")
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
            self, "CSV-Datei öffnen", "", "CSV-Dateien (*.csv);;Alle Dateien (*)"
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
            f"{self.preview.encoding.upper()} · Trennzeichen: {self.preview.delimiter!r} · "
            f"{len(self.preview.headers)} Spalten"
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
                ("Ignorieren", "ignore"),
                ("Produkt-ID", "product_id"),
                ("Beschreibung", "description"),
                ("Kontext", "context"),
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
            self._error("Bitte zuerst eine CSV-Datei auswählen.")
            return
        if self.session.status()["progress"]["total"]:
            answer = QMessageBox.question(
                self,
                "Vorhandene Daten ersetzen",
                "Der neue Import ersetzt die bisherige Produktliste. Fortfahren?",
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
                "Beschreibung und ausgewählte Kontextfelder werden zur Verarbeitung "
                "an den gewählten Cloud-Anbieter übertragen."
            )
        elif local:
            self.data_flow_label.setText(
                "Beschreibung und Kontextfelder werden an die konfigurierte "
                "Server-Adresse gesendet."
            )
        else:
            self.data_flow_label.setText(
                "Der Demo-Modus verarbeitet die Beschreibung direkt auf diesem Computer."
            )

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
            self, "CSV exportieren", "optimized-products.csv", "CSV-Dateien (*.csv)"
        )
        if name:
            self.output_path.setText(name)

    def _start_export(self) -> None:
        name = self.output_path.text().strip()
        if not name:
            self._error("Bitte einen Speicherort für die CSV-Datei auswählen.")
            return
        try:
            self.session.export_file(Path(name), include_errors=self.include_errors.isChecked())
        except Exception as exc:
            self._error(str(exc))
            return
        self._was_busy = True
        self._poll()

    def _poll(self) -> None:
        status = self.session.status()
        progress = status["progress"]
        busy = status["busy"]
        for key, label in self.stat_labels.items():
            label.setText(str(progress[key]))
        total = progress["total"]
        completed = progress["done"] + progress["error"]
        self.progress_bar.setValue(round(100 * completed / total) if total else 0)
        stage_names = {
            "idle": "Bereit",
            "importing": "CSV wird importiert",
            "optimizing": "Optimierung läuft",
            "exporting": "CSV wird exportiert",
        }
        state_text = stage_names.get(status["stage"], status["stage"])
        if status["paused"]:
            state_text = "Pausiert · laufendes Produkt wird noch abgeschlossen"
        self.stage_label.setText(f"{state_text} · {completed} von {total} verarbeitet")
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
                preview = "\n".join(str(error) for error in errors[:3])
                suffix = f"\n… und {len(errors) - 3} weitere" if len(errors) > 3 else ""
                self._error(
                    f"Import abgeschlossen, aber {len(errors)} Zeilen wurden übersprungen.\n"
                    f"{preview}{suffix}"
                )
            elif result:
                self.statusBar().showMessage("Vorgang abgeschlossen.", 7000)
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
        product = self._shown_products[row]
        self.detail.setPlainText(
            f"Original\n{product['original_description']}\n\n"
            f"Optimiert\n{product['optimized_description'] or '—'}"
            + (f"\n\nFehler\n{product['error_message']}" if product["error_message"] else "")
        )

    def _error(self, message: str) -> None:
        QMessageBox.warning(self, "PDO", message)

    def closeEvent(self, event: Any) -> None:  # noqa: N802 - Qt override
        """Stop background work before the window closes."""
        self.timer.stop()
        try:
            self.session.close()
        except RuntimeError as exc:
            self._error(str(exc))
            self.timer.start()
            event.ignore()
        else:
            event.accept()


def main() -> int:
    """Launch the desktop application or run the packaged smoke check."""
    if "--smoke-test" in sys.argv:
        from google import genai
        from openai import OpenAI
        from zhipuai import ZhipuAI

        from pdo.core.registry import list_optimizers

        assert list_optimizers()
        assert genai.Client(api_key="package-smoke-test").models
        assert OpenAI(base_url="http://127.0.0.1:1/v1", api_key="package-smoke-test").chat
        assert ZhipuAI(api_key="package-smoke-test.package-smoke-test").chat
        app = QApplication(["pdo-smoke-test"])
        with tempfile.TemporaryDirectory(prefix="pdo-smoke-") as temp_dir:
            base = Path(temp_dir)
            window = DesktopWindow(
                DesktopSession(
                    PdoConfig(data_dir=base / "data", config_file_path=base / "config.toml")
                )
            )
            window.close()
        app.quit()
        return 0
    app = QApplication(sys.argv)
    app.setApplicationName("PDO")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)
    try:
        window = DesktopWindow()
    except Exception as exc:
        QMessageBox.critical(None, "PDO konnte nicht starten", str(exc))
        return 1
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
