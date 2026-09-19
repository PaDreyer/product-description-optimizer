"""PySide6 desktop interface for the product description workflow."""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
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
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pdo.config import PdoConfig
from pdo.core.csv_format import CsvFormat
from pdo.core.provider_defaults import (
    GEMINI_MODEL,
    LOCAL_LLM_ADDRESS,
    ZHIPUAI_MODEL,
)
from pdo.desktop.controls import ContentTabs, CsvFormatEditor, button, combo
from pdo.desktop.session import CsvPreview, DesktopSession, inspect_csv, suggest_role
from pdo.exceptions import PdoError

log = logging.getLogger(__name__)

STYLESHEET = """
QWidget { font-size: 14px; }
QMainWindow, QWidget#root, QScrollArea, QScrollArea > QWidget > QWidget {
    background: #101624; color: #EFF2FA;
}
QFrame#card { background: #171F30; border: 1px solid #33415A; border-radius: 8px; }
QLabel { color: #EFF2FA; background: transparent; }
QLabel#muted { color: #ABB8CF; }
QLabel#eyebrow { color: #9D91FF; font-size: 12px; font-weight: 500; }
QLabel#headline { font-size: 24px; font-weight: 500; }
QLabel#stat { font-size: 26px; font-weight: 500; }
QPushButton {
    background: #171F30; color: #EFF2FA; border: 1px solid #33415A;
    border-radius: 7px; padding: 10px 16px; font-weight: 500;
}
QLabel#logo { background: #2A2545; color: #B3A4FF; padding: 8px; border-radius: 8px; }
QFrame#drop { background: #171F30; border: 1px dashed #33415A; border-radius: 8px; }
QPushButton#quiet { background: transparent; border: 0; color: #B3A4FF; text-align: left; }
QPushButton:hover { background: #344866; }
QPushButton:disabled { color: #8190A6; background: #1B263B; border-color: #293750; }
QPushButton#primary { background: #B3A4FF; color: #17112E; border-color: #B3A4FF; }
QPushButton#primary:hover { background: #B3A4FF; }
QLineEdit, QComboBox, QPlainTextEdit {
    background: #171F30; color: #EFF2FA; border: 1px solid #33415A;
    border-radius: 6px; padding: 8px 10px; selection-background-color: #B3A4FF;
}
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus { border-color: #B3A4FF; }
QComboBox QAbstractItemView {
    background: #171F30; color: #EFF2FA; selection-background-color: #344866;
}
QCheckBox { color: #EFF2FA; spacing: 10px; }
QTableWidget {
    background: #171F30; alternate-background-color: #1B2436; color: #EFF2FA;
    gridline-color: #33415A; border: 1px solid #33415A; border-radius: 7px;
    selection-background-color: #344866; selection-color: white;
}
QHeaderView::section {
    background: #202A3D; color: #ABB8CF; border: 0; padding: 9px; font-weight: 500;
}
QProgressBar {
    background: #171F30; border: 1px solid #33415A; border-radius: 7px;
    height: 12px; text-align: center;
}
QProgressBar::chunk { background: #B3A4FF; border-radius: 6px; }
QScrollBar:vertical { background: #101624; width: 10px; }
QScrollBar::handle:vertical { background: #344866; border-radius: 5px; min-height: 24px; }
QPushButton#step {
    background: transparent; border: 0; border-bottom: 3px solid #33415A; border-radius: 0;
}
QPushButton#step:checked { color: #B3A4FF; border-bottom-color: #B3A4FF; }
QTabWidget::pane { border: 0; }
QTabBar::tab { background: #171F30; color: #ABB8CF; padding: 10px 20px; }
QTabBar::tab:selected { color: #B3A4FF; border-bottom: 2px solid #B3A4FF; }
QLabel#error { color: #EFB783; }
QLabel#success { color: #8ED7B0; background: #18352C; border-radius: 6px; padding: 14px; }
QSpinBox { background: #171F30; color: #EFF2FA; padding: 8px; }

"""


def _label(text: str, kind: str | None = None) -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
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
    table.horizontalHeader().setDefaultAlignment(
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    )
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
    """Guided import, optimization, review, and export workflow."""

    def __init__(self, session: DesktopSession | None = None) -> None:
        super().__init__()
        self.session = session or DesktopSession()
        self.preview: CsvPreview | None = None
        self._mapping_boxes: list[tuple[str, QComboBox]] = []
        self._shown_products: list[dict[str, Any]] = []
        self._last_progress: tuple[int, ...] | None = None
        self._pending_action: str | None = None
        self._status: dict[str, Any] = {}
        self._offset = 0
        self._matching_total = 0
        self._quitting = self._closed = self._hidden_to_tray = False
        self._tray_notice_shown = self._polling = False
        self._models: list[str] = []
        self._model_address = ""
        self._status_generation = 0
        self._model_generation = 0
        self._export_generation = 0
        self._settings_from = 1
        self._export_valid = False
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pdo-ui")
        self._tray_dispatcher = _UiDispatcher(self)
        self.setWindowTitle("PDO · Product Description Optimizer")
        self.setMinimumSize(960, 700)
        self.resize(1120, 850)
        self.setStyleSheet(STYLESHEET)
        icon = QIcon(str(files("pdo.desktop").joinpath("logo.png")))
        self.setWindowIcon(icon)
        self._tray = self._create_tray(icon)
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(26, 18, 26, 14)
        outer.setSpacing(15)
        chrome = QHBoxLayout()
        chrome.addWidget(_label("pdo", "logo"))
        brand = _label("Product Description Optimizer")
        brand.setWordWrap(False)
        chrome.addWidget(brand)
        chrome.addStretch()
        self.source_label = _label("Neuer Durchlauf", "muted")
        self.source_label.setWordWrap(False)
        self.source_label.setMaximumWidth(320)
        chrome.addWidget(self.source_label)
        self.settings_button = button("Einstellungen", self._open_settings)
        chrome.addWidget(self.settings_button)
        outer.addLayout(chrome)
        steps = QHBoxLayout()
        self.nav_buttons = []
        for index, text in enumerate(
            ("1  Daten laden", "2  Optimieren", "3  Prüfen && exportieren")
        ):
            item = button(text, lambda checked=False, page=index: self._show_page(page))
            item.setObjectName("step")
            item.setCheckable(True)
            self.nav_buttons.append(item)
            steps.addWidget(item)
        outer.addLayout(steps)
        self.pages = QStackedWidget()
        self._page_actions: dict[QWidget, QHBoxLayout] = {}
        for build in (
            self._build_import,
            self._build_optimizer,
            self._build_results,
            self._build_export,
            self._build_settings,
        ):
            page = build()
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setWidget(page)
            frame = QWidget()
            frame_layout = QVBoxLayout(frame)
            frame_layout.setContentsMargins(0, 0, 0, 0)
            frame_layout.addWidget(scroll, 1)
            if page in self._page_actions:
                frame_layout.addLayout(self._page_actions[page])
            self.pages.addWidget(frame)
        outer.addWidget(self.pages, 1)
        self.daemon_label = _label("Verbindung wird hergestellt …", "muted")
        outer.addWidget(self.daemon_label)
        self._backend_changed()
        self._load_settings()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._poll_async)
        self.timer.start(900)
        self._show_page(0)
        self._poll()
        if self.backend_box.currentData() == "local_llm":
            self._check_connection()

    def _page(self, title: str, subtitle: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 14, 8, 12)
        layout.setSpacing(16)
        layout.addWidget(_label(title, "headline"))
        layout.addWidget(_label(subtitle, "muted"))
        return page, layout

    def _build_import(self) -> QWidget:
        page, layout = self._page(
            "Produktbeschreibungen importieren",
            "CSV laden, die vorgeschlagene Spaltenzuordnung prüfen und fortfahren.",
        )
        self.import_intro, intro = _card()
        self.import_intro.setObjectName("drop")
        self.import_intro.setMinimumHeight(240)
        intro.addStretch()
        intro_title = _label("Mit deiner Produktdatei beginnen", "headline")
        intro_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        intro.addWidget(intro_title)
        self.browse_button = button("CSV auswählen", self._choose_source, True)
        intro.addWidget(self.browse_button, alignment=Qt.AlignmentFlag.AlignCenter)
        intro_note = _label("Trennzeichen und Spalten werden automatisch erkannt.", "muted")
        intro_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        intro.addWidget(intro_note)
        intro.addStretch()
        layout.addWidget(self.import_intro)
        self.mapping_panel = QWidget()
        mapping = QVBoxLayout(self.mapping_panel)
        mapping.setContentsMargins(0, 0, 0, 0)
        mapping.setSpacing(14)
        row = QHBoxLayout()
        self.file_label = _label("", "muted")
        row.addWidget(self.file_label, 1)
        self.change_source_button = button("Andere CSV auswählen", self._choose_source)
        row.addWidget(self.change_source_button)
        mapping.addLayout(row)
        self.format_label = _label("Trennzeichen und Zeichenkodierung werden erkannt.", "muted")
        mapping.addWidget(self.format_label)
        self.sample_table = _table(["Spalte", "Beispiel aus der Datei", "Verwendung"])
        self.sample_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.sample_table.setColumnWidth(0, 170)
        self.sample_table.setColumnWidth(2, 260)
        self.sample_table.verticalHeader().setDefaultSectionSize(42)
        mapping.addWidget(self.sample_table, 1)
        mapping.addWidget(
            _label(
                "Nur Beschreibungen und Zusatzinfos gehen an die KI. "
                "Alle Originalspalten bleiben erhalten.",
                "muted",
            )
        )
        layout.addWidget(self.mapping_panel)
        self.mapping_panel.hide()
        layout.addStretch()
        self.import_button = button("Weiter zur Optimierung", self._start_import, True)
        actions = QHBoxLayout()
        actions.addStretch()
        actions.addWidget(self.import_button)
        self._page_actions[page] = actions
        return page

    def _build_optimizer(self) -> QWidget:
        page, layout = self._page(
            "Optimierung", "Deine Einstellungen und der aktuelle Fortschritt."
        )
        self.setup_panel = QWidget()
        setup = QVBoxLayout(self.setup_panel)
        setup.setContentsMargins(0, 0, 0, 0)
        card, provider = _card()
        row = QHBoxLayout()
        self.provider_label = _label("")
        row.addWidget(self.provider_label, 1)
        row.addWidget(button("Ändern", self._open_settings))
        provider.addLayout(row)
        self.provider_state = _label("", "muted")
        provider.addWidget(self.provider_state)
        self.data_flow_label = _label("", "muted")
        provider.addWidget(self.data_flow_label)
        setup.addWidget(card)
        self.style_label = _label("Wie sollen die Texte klingen? · Optional")
        setup.addWidget(self.style_label)
        self.style_input = QPlainTextEdit()
        self.style_input.setPlaceholderText(
            "Zum Beispiel: sachlich, verständlich, Ansprache mit du."
        )
        self.style_input.setMaximumHeight(110)
        setup.addWidget(self.style_input)
        self.text_options_toggle = button("Weitere Textvorgaben", self._toggle_text_options)
        setup.addWidget(self.text_options_toggle, alignment=Qt.AlignmentFlag.AlignLeft)
        self.text_options = QWidget()
        form = QFormLayout(self.text_options)
        self.sentences = QSpinBox()
        self.sentences.setRange(1, 20)
        self.sentences.setValue(3)
        form.addRow("Ziellänge in Sätzen", self.sentences)
        self.text_options.hide()
        setup.addWidget(self.text_options)
        self.optimize_button = button("Produkte optimieren", self._start_optimization, True)
        actions = QHBoxLayout()
        actions.addStretch()
        actions.addWidget(self.optimize_button)
        self._page_actions[page] = actions
        layout.addWidget(self.setup_panel)
        self.run_panel, run_layout = _card()
        self.run_status = _label("")
        run_layout.addWidget(self.run_status)
        self.progress_bar = QProgressBar()
        run_layout.addWidget(self.progress_bar)
        run_layout.addWidget(
            _label(
                "Du kannst das Fenster schließen. Die Verarbeitung läuft im Hintergrund weiter.",
                "muted",
            )
        )
        self.pause_button = button("Pausieren", self._toggle_pause)
        run_layout.addWidget(self.pause_button, alignment=Qt.AlignmentFlag.AlignRight)
        self.run_panel.hide()
        layout.addWidget(self.run_panel)
        layout.addStretch()
        return page

    def _toggle_text_options(self) -> None:
        self.text_options.setVisible(self.text_options.isHidden())

    def _build_results(self) -> QWidget:
        page, layout = self._page(
            "Ergebnisse prüfen", "Texte vergleichen oder Fehler gesammelt bearbeiten."
        )
        self.results_summary = _label("", "muted")
        layout.addWidget(self.results_summary)
        self.result_tabs = ContentTabs()
        products = QWidget()
        product_layout = QVBoxLayout(products)
        filters = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Produkt-ID oder Text suchen")
        self.search_input.returnPressed.connect(self._search_products)
        filters.addWidget(self.search_input, 1)
        self.status_filter = combo(
            [
                ("Alle Produkte", None),
                ("Erfolgreich", "done"),
                ("Fehlerhaft", "error"),
                ("Ausstehend", "pending"),
            ]
        )
        self.status_filter.currentIndexChanged.connect(self._search_products)
        filters.addWidget(self.status_filter)
        filters.addWidget(button("Suchen", self._search_products))
        product_layout.addLayout(filters)
        self.results_table = _table(["Produkt-ID", "Status", "Original (Vorschau)"])
        self.results_table.setMinimumHeight(280)
        self.results_table.setMinimumWidth(250)
        self.results_table.setMaximumWidth(290)
        self.results_table.setColumnWidth(0, 145)
        self.results_table.setColumnHidden(2, True)
        self.results_table.itemSelectionChanged.connect(self._show_selected_product)
        review = QHBoxLayout()
        review.setSpacing(20)
        review.addWidget(self.results_table)
        detail_column = QVBoxLayout()
        self.product_title = _label("Produkt auswählen", "muted")
        detail_column.addWidget(self.product_title)
        paging = QHBoxLayout()
        self.previous_button = button("Vorherige 100", lambda: self._change_page(-100))
        self.next_button = button("Nächste 100", lambda: self._change_page(100))
        paging.addWidget(self.previous_button)
        self.page_label = _label("", "muted")
        paging.addWidget(self.page_label, 1)
        paging.addWidget(self.next_button)

        compare = QHBoxLayout()
        self.original_detail = QPlainTextEdit()
        self.detail = QPlainTextEdit()
        for title, editor in (("Original", self.original_detail), ("Optimiert", self.detail)):
            column = QVBoxLayout()
            column.addWidget(_label(title, "muted"))
            editor.setReadOnly(True)
            editor.setMinimumHeight(220)
            column.addWidget(editor)
            compare.addLayout(column)
        detail_column.addLayout(compare, 1)
        review.addLayout(detail_column, 1)
        product_layout.addLayout(review, 1)
        product_layout.addLayout(paging)
        self.result_tabs.addTab(products, "Produkte")
        errors = QWidget()
        error_layout = QVBoxLayout(errors)
        self.no_errors = _label(
            "Keine offenen Fehler. Deine Ergebnisse sind bereit zum Export.", "success"
        )
        error_layout.addWidget(self.no_errors)
        error_layout.addWidget(
            _label(
                "Jede Auswahl umfasst alle Produkte der Fehlergruppe. "
                "Erfolgreiche Ergebnisse bleiben erhalten.",
                "muted",
            )
        )
        actions = QHBoxLayout()
        self.select_errors = QCheckBox("Alle wiederholbaren Gruppen auswählen")
        self.select_errors.setChecked(True)
        self.select_errors.clicked.connect(self._select_all_errors)
        actions.addWidget(self.select_errors, 1)
        self.retry_button = button("Ausgewählte erneut verarbeiten", self._retry_errors, True)
        actions.addWidget(self.retry_button)
        error_layout.addLayout(actions)
        self.errors_table = _table(["Fehlerursache", "Produkte", "Nächster Schritt"])
        self.errors_table.setColumnWidth(0, 260)
        self.errors_table.setColumnWidth(1, 105)
        self.errors_table.setMinimumHeight(150)
        self.errors_table.setMaximumHeight(290)
        self.errors_table.itemChanged.connect(self._error_selection_changed)
        error_layout.addWidget(self.errors_table, 1)
        corrections = QHBoxLayout()
        self.correction_export_button = button(
            "Quelldaten zur Korrektur exportieren", lambda: self._open_export("corrections")
        )
        self.correction_import_button = button("Korrigierte CSV einlesen", self._import_corrections)
        corrections.addWidget(self.correction_export_button)
        corrections.addWidget(self.correction_import_button)
        error_layout.addLayout(corrections)
        self.correction_note = _label("", "muted")
        error_layout.addWidget(self.correction_note)
        error_layout.addStretch(1)
        self.error_export_button = button(
            "Alle Fehler exportieren", lambda: self._open_export("errors")
        )
        self.error_export_button.hide()
        self.result_tabs.currentChanged.connect(
            lambda index: self.error_export_button.setVisible(index == 1)
        )
        self.result_tabs.addTab(errors, "Fehler")
        layout.addWidget(self.result_tabs, 1)
        row = QHBoxLayout()
        self.new_button = button("Neue CSV", self._new_batch)
        row.addWidget(self.new_button)
        row.addWidget(self.error_export_button)
        row.addStretch()
        self.export_button = button("Weiter zum Export", lambda: self._open_export("done"), True)
        row.addWidget(self.export_button)
        self._page_actions[page] = row
        return page

    def _build_export(self) -> QWidget:
        page, layout = self._page(
            "CSV exportieren", "Eine neue Datei für dein Zielsystem erstellen."
        )
        self.export_title = layout.itemAt(0).widget()
        self.export_subtitle = layout.itemAt(1).widget()
        self.export_success = _label("", "success")
        self.export_success.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.export_success.setMinimumHeight(220)
        self.export_success.hide()
        layout.addWidget(self.export_success)
        self.export_body = QWidget()
        body = QVBoxLayout(self.export_body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(16)
        layout.addWidget(self.export_body)
        layout.addStretch()
        self.export_scope = combo(
            [
                ("Nur erfolgreiche Produkte", "done"),
                ("Alle Produkte", "all"),
                ("Fehlerliste mit Quelldaten", "errors"),
                ("Quelldaten zur Korrektur", "corrections"),
            ]
        )
        self.export_scope.currentIndexChanged.connect(self._refresh_export_preview)
        body.addWidget(self.export_scope)
        self.export_note = _label("", "muted")
        body.addWidget(self.export_note)
        card, card_layout = _card()
        self.format_editor = CsvFormatEditor()
        self.format_editor.changed.connect(self._schedule_preview)
        card_layout.addWidget(self.format_editor)
        body.addWidget(card)
        body.addWidget(_label("Vorschau · zwei Produkte aus deinen Daten"))
        self.export_preview = QPlainTextEdit()
        self.export_preview.setReadOnly(True)
        self.export_preview.setMinimumHeight(110)
        self.export_preview.setMaximumHeight(190)
        body.addWidget(self.export_preview)
        self.export_error = _label("", "error")
        body.addWidget(self.export_error)
        row = QHBoxLayout()
        row.addWidget(button("Zurück zu den Ergebnissen", lambda: self._show_page(2)))
        row.addStretch()
        self.save_button = button("Speichern unter …", self._start_export, True)
        row.addWidget(self.save_button)
        self.prepare_export_button = button(
            "Weiteren Export vorbereiten",
            lambda: self._open_export(self.export_scope.currentData()),
            True,
        )
        self.prepare_export_button.hide()
        row.addWidget(self.prepare_export_button)
        self._page_actions[page] = row
        self.export_timer = QTimer(self)
        self.export_timer.setSingleShot(True)
        self.export_timer.timeout.connect(self._refresh_export_preview)
        return page

    def _build_settings(self) -> QWidget:
        page, layout = self._page(
            "KI-Verbindung",
            "Einmal einrichten. Deine Auswahl wird für weitere Durchläufe gespeichert.",
        )
        self.settings_form = QFormLayout()
        form = self.settings_form
        form.setSpacing(16)
        self.backend_box = combo(
            [
                ("Lokaler KI-Server", "local_llm"),
                ("Google Gemini", "gemini"),
                ("ZhipuAI", "zhipuai"),
                ("Demo · nur Großschreibung", "dummy"),
            ]
        )
        form.addRow("Anbieter", self.backend_box)
        self.key_input = QLineEdit()
        self.key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_input.setPlaceholderText("Gespeicherten Schlüssel behalten / Umgebung verwenden")
        form.addRow("API-Schlüssel", self.key_input)
        self.address_input = QLineEdit(LOCAL_LLM_ADDRESS)
        form.addRow("Serveradresse", self.address_input)
        self.connection_button = button("Verbindung prüfen", self._check_connection)
        form.addRow(self.connection_button)
        self.connection_label = _label("", "muted")
        form.addRow(self.connection_label)
        self.model_box = QComboBox()
        form.addRow("Modell auswählen", self.model_box)
        self.manual_model = QCheckBox("Modell manuell festlegen · Erweitert")
        form.addRow(self.manual_model)
        self.model_input = QLineEdit()
        self.model_input.setPlaceholderText("Modellkennung des Anbieters")
        form.addRow("Modellkennung", self.model_input)
        self.settings_note = _label("", "muted")
        form.addRow(self.settings_note)
        layout.addLayout(form)
        layout.addStretch()
        row = QHBoxLayout()
        row.addWidget(button("Abbrechen", self._cancel_settings))
        row.addStretch()
        self.settings_save_button = button("Übernehmen", self._save_settings, True)
        row.addWidget(self.settings_save_button)
        self._page_actions[page] = row
        self.backend_box.currentIndexChanged.connect(self._backend_changed)
        self.manual_model.toggled.connect(self._provider_visibility)
        self.model_box.currentIndexChanged.connect(self._update_provider)
        self.address_input.textChanged.connect(self._address_changed)
        return page

    def _provider_visibility(self) -> None:
        backend = self.backend_box.currentData()
        local, cloud = backend == "local_llm", backend in ("gemini", "zhipuai")
        for widget, visible in (
            (self.key_input, cloud),
            (self.address_input, local),
            (self.connection_button, local),
            (self.connection_label, local),
            (self.manual_model, backend != "dummy"),
            (self.model_input, backend != "dummy" and self.manual_model.isChecked()),
            (self.model_box, local and len(self._models) > 1 and not self.manual_model.isChecked()),
        ):
            self.settings_form.setRowVisible(widget, visible)
        self._update_provider()

    def _backend_changed(self, _: int = 0) -> None:
        backend = self.backend_box.currentData()
        options = self.session.config.options
        self.key_input.clear()
        self.manual_model.setChecked(options.get(f"{backend}.manual_model", "false") == "true")
        defaults = {"gemini": GEMINI_MODEL, "zhipuai": ZHIPUAI_MODEL, "local_llm": ""}
        self.model_input.setText(options.get(f"{backend}.model", defaults.get(backend, "")))
        self._provider_visibility()

    def _load_settings(self, *, preserve_text: bool = False) -> None:
        config = self.session.config
        self.backend_box.setCurrentIndex(max(0, self.backend_box.findData(config.optimizer)))
        self.address_input.setText(config.options.get("local_llm.address", LOCAL_LLM_ADDRESS))
        if not preserve_text:
            self.style_input.setPlainText(config.options.get("style_instructions", ""))
            self.sentences.setValue(int(config.options.get("target_sentences", 3)))
        self._backend_changed()
        saved_model = config.options.get("local_llm.model", "")
        if saved_model in self._models:
            self.model_box.setCurrentText(saved_model)

    def _address_changed(self) -> None:
        self._models = []
        self._model_address = ""
        self._model_generation += 1
        self.connection_button.setEnabled(True)
        self.connection_label.setText("Verbindung noch nicht geprüft.")
        self._provider_visibility()

    def _update_provider(self) -> None:
        backend = self.backend_box.currentData()
        self.provider_label.setText(self.backend_box.currentText())
        demo = backend == "dummy"
        for widget in (self.style_input, self.style_label, self.text_options_toggle):
            widget.setVisible(not demo)
        if demo:
            self.text_options.hide()
        text = {
            "local_llm": "Beschreibungen und Zusatzinfos gehen an die angegebene Serveradresse.",
            "gemini": "Beschreibungen und Zusatzinfos werden an Google Gemini gesendet.",
            "zhipuai": "Beschreibungen und Zusatzinfos werden an ZhipuAI gesendet.",
            "dummy": "Demo verarbeitet auf diesem Computer und schreibt nur Großbuchstaben.",
        }[backend]
        self.data_flow_label.setText(text)
        self.settings_note.setText(text)
        if backend == "local_llm":
            if self.manual_model.isChecked():
                self.provider_state.setText("Manuelle Modellkennung aus den Einstellungen")
            elif len(self._models) == 1:
                self.provider_state.setText(
                    f"Verbunden · {self._models[0]} · automatisch ausgewählt"
                )
            elif len(self._models) > 1:
                self.provider_state.setText(f"Verbunden · {self.model_box.currentText()}")
            else:
                self.provider_state.setText("Verbindung in den Einstellungen prüfen.")
        elif demo:
            self.provider_state.setText("Demo ohne KI")
        else:
            configured = self.session.config.options.get(f"{backend}.api_key") or os.environ.get(
                {"gemini": "GEMINI_API_KEY", "zhipuai": "ZHIPUAI_API_KEY"}[backend]
            )
            model = (
                "Manuell gewähltes Modell" if self.manual_model.isChecked() else "Standardmodell"
            )
            self.provider_state.setText(
                f"Zugang hinterlegt · {model}"
                if configured
                else "API-Schlüssel in den Einstellungen hinterlegen."
            )

    def _check_connection(self) -> None:
        address = self.address_input.text().strip()
        self._model_generation += 1
        generation = self._model_generation
        self.connection_button.setEnabled(False)
        self.connection_label.setText("Verbindung wird geprüft …")

        def finished(models: list[str]) -> None:
            if generation != self._model_generation:
                return
            self._models, self._model_address = models, address
            self.model_box.clear()
            self.model_box.addItems(models)
            previous = self.session.config.options.get("local_llm.model", "")
            if previous in models:
                self.model_box.setCurrentText(previous)
            self.connection_label.setText(f"Verbunden · {len(models)} Modell(e) erkannt")
            self.connection_button.setEnabled(True)
            self._provider_visibility()

        def failed(exc: Exception) -> None:
            if generation == self._model_generation:
                self.connection_label.setText(
                    str(exc) + " Manuelle Angabe unter Erweitert möglich."
                )
                self.connection_button.setEnabled(True)

        self._submit(lambda: self.session.models(address), finished, failed)

    def _provider_settings(self) -> dict[str, str]:
        backend = self.backend_box.currentData()
        values = {
            "style_instructions": self.style_input.toPlainText().strip(),
            "target_sentences": str(self.sentences.value()),
        }
        if backend == "dummy":
            return values
        if backend == "local_llm":
            values["local_llm.address"] = self.address_input.text().strip()
            if not self.manual_model.isChecked():
                if not self._models or self._model_address != values["local_llm.address"]:
                    raise ValueError(
                        "Prüfe zuerst den lokalen Server oder lege das Modell unter Erweitert fest."
                    )
                values["local_llm.model"] = self.model_box.currentText()
        elif self.key_input.text().strip():
            values[f"{backend}.api_key"] = self.key_input.text().strip()
        values[f"{backend}.manual_model"] = str(self.manual_model.isChecked()).lower()
        if self.manual_model.isChecked():
            if not self.model_input.text().strip():
                raise ValueError(
                    "Gib eine Modellkennung ein oder verwende die automatische Auswahl."
                )
            values[f"{backend}.model"] = self.model_input.text().strip()
        elif backend != "local_llm":
            values[f"{backend}.model"] = {"gemini": GEMINI_MODEL, "zhipuai": ZHIPUAI_MODEL}[backend]
        return values

    def _open_settings(self) -> None:
        self._settings_from = self.pages.currentIndex()
        self._show_page(4)

    def _cancel_settings(self) -> None:
        self._show_page(self._settings_from)

    def _save_settings(self) -> None:
        try:
            self.session.save_settings(self.backend_box.currentData(), self._provider_settings())
            self._show_page(self._settings_from)
            self._update_provider()
        except Exception as exc:
            self._error(str(exc))

    def _show_page(self, index: int) -> None:
        if self.pages.currentIndex() == 4 and index != 4:
            self._load_settings(preserve_text=True)
            if self.backend_box.currentData() == "local_llm" and not self._models:
                self._check_connection()
        self.pages.setCurrentIndex(index)
        for position, item in enumerate(self.nav_buttons):
            item.setChecked(position == (2 if index == 3 else index))
        if index == 2:
            self._refresh_products()
        if index == 3:
            self._refresh_export_preview()

    def _choose_source(self) -> bool:
        name, _ = QFileDialog.getOpenFileName(
            self, "CSV auswählen", "", "Textdateien (*.csv *.tsv *.txt);;Alle Dateien (*)"
        )
        if not name:
            return False
        try:
            self.preview = inspect_csv(Path(name))
            self.file_label.setText(self.preview.path.name)
            self.format_label.setText(
                f"{self.preview.encoding} · Trennzeichen {self.preview.delimiter!r} · "
                f"{len(self.preview.headers)} Spalten"
            )
            self._mapping_boxes = []
            self.sample_table.setRowCount(len(self.preview.headers))
            for row, name in enumerate(self.preview.headers):
                values = [
                    ("Produkt-ID", "product_id"),
                    ("Beschreibung", "description"),
                    ("Zusatzinfo für die KI", "context"),
                    ("Nicht für die KI verwenden", "ignore"),
                ]
                selector = combo(values)
                selector.setCurrentIndex(selector.findData(suggest_role(name)))
                self._mapping_boxes.append((name, selector))
                self.sample_table.setItem(row, 0, QTableWidgetItem(name))
                sample = (
                    self.preview.rows[0][row]
                    if self.preview.rows and row < len(self.preview.rows[0])
                    else ""
                )
                self.sample_table.setItem(row, 1, QTableWidgetItem(sample[:250]))
                self.sample_table.setCellWidget(row, 2, selector)
            self.sample_table.setFixedHeight(min(420, 44 + 42 * len(self.preview.headers)))
            self.import_intro.hide()
            self.mapping_panel.show()
            self.import_button.show()
            self.import_button.setEnabled(True)
            return True
        except Exception as exc:
            self._error(str(exc))
            return False

    def _start_import(self) -> None:
        if not self.preview:
            return
        mappings = [
            {"role": box.currentData(), "csv_column_name": name, "display_name": name}
            for name, box in self._mapping_boxes
            if box.currentData() != "ignore"
        ]
        if not any(m["role"] == "description" for m in mappings):
            self._error("Wähle mindestens eine Beschreibungsspalte.")
            return
        if sum(m["role"] == "product_id" for m in mappings) > 1:
            self._error("Wähle höchstens eine Produkt-ID-Spalte.")
            return
        if (
            self._status.get("progress", {}).get("total")
            and QMessageBox.question(
                self,
                "Aktuellen Durchlauf ersetzen",
                "Die neue CSV ersetzt den aktuellen Durchlauf. "
                "Exportiere vorher die Ergebnisse, die du behalten möchtest. Neue CSV laden?",
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self._start_action("import", lambda: self.session.import_file(self.preview, mappings))

    def _start_action(self, action: str, callback: Any) -> None:
        try:
            callback()
            self._pending_action = action
            self._poll()
        except Exception as exc:
            self._error(str(exc))

    def _start_optimization(self) -> None:
        try:
            settings = self._provider_settings()
        except Exception as exc:
            self._error(str(exc))
            self._open_settings()
            return
        self._start_action(
            "optimize", lambda: self.session.optimize(self.backend_box.currentData(), settings)
        )

    def _toggle_pause(self) -> None:
        callback = self.session.resume if self._status.get("paused") else self.session.pause
        try:
            callback()
            self._poll()
        except Exception as exc:
            self._error(str(exc))

    def _new_batch(self) -> None:
        previous_page = self.pages.currentIndex()
        self._show_page(0)
        if not self._choose_source():
            self._show_page(previous_page)

    def _change_page(self, delta: int) -> None:
        self._offset = max(0, self._offset + delta)
        self._refresh_products()

    def _search_products(self) -> None:
        self._offset = 0
        self._refresh_products()

    def _refresh_products(self) -> None:
        try:
            page = self.session.product_page(
                self._offset, self.status_filter.currentData(), self.search_input.text()
            )
            self._shown_products, self._matching_total = page["products"], page["total"]
            if self._offset and not self._shown_products:
                self._offset = 0
                self._refresh_products()
                return
            self.results_table.blockSignals(True)
            self.results_table.setRowCount(len(self._shown_products))
            names = {
                "done": "Fertig",
                "error": "Fehler",
                "pending": "Ausstehend",
                "processing": "In Arbeit",
            }
            for row, product in enumerate(self._shown_products):
                for column, text in enumerate(
                    (
                        product["product_id_value"],
                        names[product["status"]],
                        product["original_description"],
                    )
                ):
                    self.results_table.setItem(row, column, QTableWidgetItem(text))
            self.results_table.blockSignals(False)
            self.page_label.setText(
                f"{self._offset + 1 if self._shown_products else 0} bis "
                f"{self._offset + len(self._shown_products)} von {self._matching_total}"
            )
            self.previous_button.setEnabled(self._offset > 0)
            self.next_button.setEnabled(self._offset + 100 < self._matching_total)
            if self._shown_products:
                self.results_table.selectRow(0)
                self._show_selected_product()
            else:
                self.product_title.setText("Keine passenden Produkte")
                self.original_detail.clear()
                self.detail.clear()
        except Exception as exc:
            self.daemon_label.setText(str(exc))

    def _show_selected_product(self) -> None:
        row = self.results_table.currentRow()
        if not 0 <= row < len(self._shown_products):
            return
        try:
            product = self.session.product(self._shown_products[row]["id"])
            identifier = product["product_id_value"]
            self.product_title.setText(f"Produkt {identifier[:64]}")
            self.product_title.setToolTip(identifier)
            self.original_detail.setPlainText(
                product["original_description"]
                + ("\n[… gekürzt]" if product["original_truncated"] else "")
            )
            self.detail.setPlainText(
                (
                    product["optimized_description"]
                    or product["error_message"]
                    or "Noch nicht verarbeitet"
                )
                + (
                    "\n[… gekürzt]"
                    if product["optimized_truncated"] or product["error_truncated"]
                    else ""
                )
            )
        except Exception as exc:
            self._error(str(exc))

    def _refresh_errors(self) -> None:
        self.errors_table.blockSignals(True)
        groups = self._status.get("error_groups", [])
        self.no_errors.setVisible(not groups)
        for widget in (
            self.select_errors,
            self.retry_button,
            self.errors_table,
            self.correction_export_button,
            self.correction_import_button,
            self.correction_note,
        ):
            widget.setVisible(bool(groups))
        self.errors_table.setRowCount(len(groups))
        for row, group in enumerate(groups):
            item = QTableWidgetItem(group["label"])
            item.setData(Qt.ItemDataRole.UserRole, group)
            if group["retryable"]:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked)
            self.errors_table.setItem(row, 0, item)
            self.errors_table.setItem(row, 1, QTableWidgetItem(str(group["count"])))
            self.errors_table.setItem(row, 2, QTableWidgetItem(group["guidance"]))
        self.errors_table.resizeRowsToContents()
        for row in range(len(groups)):
            self.errors_table.setRowHeight(row, max(48, self.errors_table.rowHeight(row)))
        height = self.errors_table.horizontalHeader().height() + 4
        height += sum(self.errors_table.rowHeight(row) for row in range(len(groups)))
        self.errors_table.setFixedHeight(height)
        self.result_tabs.fit_current_page()
        self.errors_table.blockSignals(False)
        self._error_selection_changed()

    def _selected_groups(self) -> list[dict[str, Any]]:
        return [
            self.errors_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            for row in range(self.errors_table.rowCount())
            if self.errors_table.item(row, 0).checkState() == Qt.CheckState.Checked
        ]

    def _error_selection_changed(self) -> None:
        selected = self._selected_groups()
        count = sum(group["count"] for group in selected)
        available = sum(g["retryable"] for g in self._status.get("error_groups", []))
        state = Qt.CheckState.Unchecked
        if selected:
            state = (
                Qt.CheckState.Checked
                if len(selected) == available
                else Qt.CheckState.PartiallyChecked
            )
        self.select_errors.blockSignals(True)
        self.select_errors.setCheckState(state)
        self.select_errors.blockSignals(False)
        self.retry_button.setText(f"{count:,} ausgewählte erneut verarbeiten".replace(",", "."))
        self.retry_button.setEnabled(count > 0 and not self._status.get("busy"))

    def _select_all_errors(self, checked: bool) -> None:
        for row in range(self.errors_table.rowCount()):
            item = self.errors_table.item(row, 0)
            if item.data(Qt.ItemDataRole.UserRole)["retryable"]:
                item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)

    def _retry_errors(self) -> None:
        groups = [group["kind"] for group in self._selected_groups()]
        self._start_action("optimize", lambda: self.session.retry_errors(groups))

    def _import_corrections(self) -> None:
        name, _ = QFileDialog.getOpenFileName(
            self, "Korrigierte CSV einlesen", "", "Textdateien (*.csv *.tsv *.txt)"
        )
        if name:
            try:
                preview = inspect_csv(Path(name))
                self._start_action("correction", lambda: self.session.import_corrections(preview))
            except Exception as exc:
                self._error(str(exc))

    def _open_export(self, scope: str) -> None:
        self.export_success.hide()
        self.export_body.show()
        self.save_button.show()
        self.prepare_export_button.hide()
        self.export_subtitle.setText("Eine neue Datei für dein Zielsystem erstellen.")
        self.export_scope.setCurrentIndex(self.export_scope.findData(scope))
        self._show_page(3)

    def _schedule_preview(self) -> None:
        if hasattr(self, "export_timer"):
            self.export_success.hide()
            self._export_generation += 1
            self._export_valid = False
            self.save_button.setEnabled(False)
            self.export_timer.start(200)

    def _refresh_export_preview(self) -> None:
        if not hasattr(self, "export_preview"):
            return
        self._export_generation += 1
        generation = self._export_generation
        self._export_valid = False
        self.save_button.setEnabled(False)
        try:
            format_ = self.format_editor.value()
        except Exception as exc:
            self.export_error.setText(str(exc))
            self.export_preview.setPlainText("Für die Vorschau ein gültiges CSV-Format wählen.")
            return
        scope = self.export_scope.currentData()
        self.export_title.setText(
            {
                "done": "Ergebnisse exportieren",
                "all": "Ergebnisse exportieren",
                "errors": "Fehlerliste exportieren",
                "corrections": "Korrekturdatei exportieren",
            }[scope]
        )
        counts = self._status.get("progress", {})
        n = counts.get("error", 0)
        export_count = {
            "done": counts.get("done", 0),
            "all": counts.get("total", 0),
            "errors": n,
            "corrections": sum(
                g["count"]
                for g in self._status.get("error_groups", [])
                if g["kind"] == "missing_data"
            ),
        }[scope]
        unit = "Produkt" if export_count == 1 else "Produkte"
        self.save_button.setText(f"{export_count:,} {unit} speichern unter …".replace(",", "."))
        notes = {
            "done": (f"Alle Originalspalten + optimierter Text + Status. {n} Fehler ausgelassen."),
            "all": (
                f"Alle Originalspalten + optimierter Text + Status. {n} Fehler ohne neuen Text."
            ),
            "errors": "Fehlerhafte Produkte mit allen Originalspalten, Fehlerursache und Status.",
            "corrections": (
                "Produkte ohne Quelldaten, mit allen Originalspalten. Produkt-IDs beibehalten."
            ),
        }
        self.export_note.setText(notes[scope])
        self.export_error.clear()

        def finished(text: str) -> None:
            if generation != self._export_generation:
                return
            self.export_preview.setPlainText(text.replace("\t", "⇥"))
            self._export_valid = not text.startswith("Keine Produkte")
            self.save_button.setEnabled(self._export_valid and not self._status.get("busy"))

        def failed(exc: Exception) -> None:
            if generation == self._export_generation:
                self.export_error.setText(str(exc))
                self.export_preview.clear()

        self._submit(lambda: self.session.export_preview(format_, scope), finished, failed)

    def _start_export(self) -> None:
        try:
            format_ = self.format_editor.value()
            suffix = {"errors": "-fehler", "corrections": "-korrektur"}.get(
                self.export_scope.currentData(), "-optimiert"
            )
            source = Path(self._status.get("source_file") or "produkte.csv")
            name, _ = QFileDialog.getSaveFileName(
                self,
                "CSV speichern",
                str(source.with_name(source.stem + suffix + ".csv")),
                "Textdateien (*.csv *.tsv *.txt)",
            )
            if name:
                self._start_action(
                    "export",
                    lambda: self.session.export_file(
                        Path(name),
                        format_=format_,
                        scope=self.export_scope.currentData(),
                        remember_format=self.format_editor.remember.isChecked(),
                    ),
                )
        except Exception as exc:
            self._error(str(exc))

    def _submit(self, work: Any, finished: Any, failed: Any = None) -> None:
        if self._closed:
            return
        future = self._pool.submit(work)

        def deliver() -> None:
            if self._closed:
                return
            try:
                value = future.result()
            except Exception as exc:
                (failed or (lambda error: self._error(str(error))))(exc)
            else:
                finished(value)

        def completed(_: Any) -> None:
            if not self._closed:
                self._tray_dispatcher.invoke.emit(deliver)

        future.add_done_callback(completed)

    def _poll_async(self) -> None:
        if self._polling or self._closed:
            return
        self._polling = True
        generation = self._status_generation

        def failed(exc: Exception) -> None:
            self._polling = False
            if generation == self._status_generation:
                self.daemon_label.setText(f"Hintergrunddienst nicht erreichbar: {exc}")

        def finished(status: dict[str, Any]) -> None:
            self._polling = False
            if generation == self._status_generation:
                self._apply_status(status)

        self._submit(self.session.status, finished, failed)

    def _poll(self) -> None:
        self._status_generation += 1
        try:
            self._apply_status(self.session.status())
        except Exception as exc:
            self.daemon_label.setText(f"Hintergrunddienst nicht erreichbar: {exc}")

    def _apply_status(self, status: dict[str, Any]) -> None:
        if self._hidden_to_tray and not self._tray_available():
            self._show_from_tray()
        first = not self._status
        old_source = self._status.get("source_file")
        self._status = status
        progress = status["progress"]
        busy, total = status["busy"], progress["total"]
        count = progress["done"] + progress["error"]
        self.daemon_label.setText(
            f"Fortschritt lokal gespeichert · {count:,} von {total:,} verarbeitet".replace(",", ".")
        )
        self.source_label.setText(
            Path(status["source_file"]).name if status.get("source_file") else "Neuer Durchlauf"
        )
        self.results_summary.setText(
            (
                f"{total:,} Produkte · {progress['done']:,} erfolgreich · "
                f"{progress['error']:,} Fehler"
            ).replace(",", ".")
        )
        self.result_tabs.setTabText(1, f"Fehler ({progress['error']})")
        self.settings_button.setEnabled(not busy)
        self.import_button.setEnabled(self.preview is not None and not busy)
        self.browse_button.setEnabled(not busy)
        self.change_source_button.setEnabled(not busy)
        self.import_button.setVisible(self.preview is not None)
        self.optimize_button.setEnabled(progress["pending"] > 0 and not busy)
        self.optimize_button.setVisible(not busy)
        pending = progress["pending"]
        self.optimize_button.setText(
            f"{pending:,} {'Produkt' if pending == 1 else 'Produkte'} optimieren".replace(",", ".")
        )
        self.export_button.setEnabled(progress["done"] + progress["error"] > 0 and not busy)
        self.new_button.setEnabled(not busy)
        self.save_button.setEnabled(self._export_valid and not busy)
        self.format_editor.setEnabled(not busy)
        self.export_scope.setEnabled(not busy)
        self.setup_panel.setVisible(not busy)
        self.run_panel.setVisible(busy)
        self.progress_bar.setRange(0, total or 1)
        self.progress_bar.setValue(count)
        state = {"importing": "CSV wird eingelesen", "exporting": "CSV wird gespeichert"}.get(
            status["stage"], "Verarbeitung läuft"
        )
        if status["paused"]:
            state = "Pausiert · aktuelles Produkt wird noch abgeschlossen"
        self.run_status.setText(f"{state} · {count} von {total}")
        self.pause_button.setText("Fortsetzen" if status["paused"] else "Pausieren")
        self.pause_button.setEnabled(busy and status["stage"] == "optimizing")
        self.nav_buttons[0].setEnabled(not busy)
        self.nav_buttons[1].setEnabled(total > 0)
        self.nav_buttons[2].setEnabled(count > 0 and not busy)
        key = tuple(progress[k] for k in ("total", "done", "pending", "processing", "error"))
        if key != self._last_progress or (self._pending_action == "correction" and not busy):
            self._last_progress = key
            self._refresh_products()
            self._refresh_errors()
        self._error_selection_changed()
        self.select_errors.setEnabled(not busy)
        self.errors_table.setEnabled(not busy)
        missing = any(g["kind"] == "missing_data" for g in status.get("error_groups", []))
        self.correction_export_button.setEnabled(missing and not busy)
        self.correction_import_button.setEnabled(
            status.get("can_correct", False) and progress["error"] > 0 and not busy
        )
        self.correction_note.setText(
            "Korrekturimport ordnet Zeilen über eindeutige Produkt-IDs zu."
            if status.get("can_correct")
            else "Korrekturimport benötigt eine zugeordnete Produkt-ID-Spalte."
        )
        self.error_export_button.setEnabled(progress["error"] > 0 and not busy)
        if (
            first
            or old_source != status.get("source_file")
            or (self._pending_action == "import" and not busy)
        ):
            source_format = CsvFormat.from_dict(status.get("source_format") or {})
            self.format_editor.source_format = source_format
            saved = self.session.config.options.get("export.format")
            try:
                self.format_editor.set_format(
                    CsvFormat.from_dict(json.loads(saved)) if saved else source_format
                )
            except (ValueError, PdoError):
                self.format_editor.set_format(source_format)
        if busy and status["stage"] == "optimizing":
            # Reopened clients also follow completion of an already running job.
            self._pending_action = self._pending_action or "optimize"
            if self.pages.currentIndex() != 1:
                self._show_page(1)
        if self._pending_action and not busy:
            action, self._pending_action = self._pending_action, None
            result = status["last_result"]
            if result.get("error"):
                self._error(result["error"])
            elif action == "import":
                self._offset = 0
                self._show_page(1)
                if result.get("skipped_count"):
                    self._error(
                        f"{result['skipped_count']} Zeilen konnten nicht importiert werden. "
                        + "\n".join(result.get("errors", [])[:3])
                    )
            elif action in {"optimize", "correction"}:
                self._show_page(2)
                if progress["error"]:
                    self.result_tabs.setCurrentIndex(1)
            elif action == "export":
                self.export_error.setText(
                    f"Gespeichert: {result.get('output_path', '')} · "
                    f"{result.get('total_exported', 0)} Produkte"
                )
                self.export_success.setText(
                    "Export abgeschlossen\n"
                    + f"{result.get('total_exported', 0):,}".replace(",", ".")
                    + " Produkte · "
                    + Path(result.get("output_path", "")).name
                )
                self.export_success.show()
                self.export_title.setText("Export abgeschlossen")
                self.export_subtitle.setText("Deine CSV-Datei wurde gespeichert.")
                self.export_body.hide()
                self.save_button.hide()
                self.prepare_export_button.show()
                self.pages.widget(3).findChild(QScrollArea).verticalScrollBar().setValue(0)
        elif first and total:
            self._show_page(1 if progress["pending"] or busy else 2)

    def _error(self, message: str) -> None:
        QMessageBox.warning(self, "PDO", message)

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
        self._closed = True
        self._pool.shutdown(wait=False, cancel_futures=True)
        self.timer.stop()
        self.export_timer.stop()
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
