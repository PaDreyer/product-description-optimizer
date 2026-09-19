from __future__ import annotations

__doc__ = "Reusable controls for the approved desktop workflow."

from typing import Any

from PySide6.QtCore import QPointF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QStyle,
    QStyleOptionButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from pdo.core.csv_format import CsvFormat

COMBO_POPUP_STYLESHEET = """
    background: #171F30;
    border: 1px solid #33415A;
"""


class StyledCheckBox(QCheckBox):
    """Checkbox with a high-contrast checked state in the dark desktop theme."""

    def paintEvent(self, event: Any) -> None:  # noqa: N802 - Qt override
        """Paint the platform control, then replace its indicator with a clear checkmark."""
        super().paintEvent(event)

        option = QStyleOptionButton()
        self.initStyleOption(option)
        indicator = self.style().subElementRect(
            QStyle.SubElement.SE_CheckBoxIndicator, option, self
        )
        outline = indicator.adjusted(1, 1, -1, -1)
        checked = self.checkState() == Qt.CheckState.Checked
        enabled = self.isEnabled()
        border = "#B3A4FF" if checked and enabled else "#647695"
        background = "#7563D7" if checked and enabled else "#171F30"
        checkmark = "#FFFFFF" if enabled else "#EFF2FA"
        if checked and not enabled:
            background = "#46536A"

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Cover the native indicator completely before drawing our theme. This
        # prevents its light frame from peeking out around an empty checkbox.
        painter.fillRect(indicator, QColor(background))
        painter.setPen(QPen(QColor(border), 2))
        painter.setBrush(QColor(background))
        painter.drawRoundedRect(outline, 4, 4)
        if checked:
            painter.setPen(
                QPen(QColor(checkmark), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            )
            painter.drawLine(
                QPointF(outline.left() + 4, outline.center().y()),
                QPointF(outline.center().x() - 1, outline.bottom() - 4),
            )
            painter.drawLine(
                QPointF(outline.center().x() - 1, outline.bottom() - 4),
                QPointF(outline.right() - 3, outline.top() + 4),
            )
        painter.end()


def label(text: str, kind: str | None = None) -> QLabel:
    """Create a wrapping label with an optional visual role."""
    result = QLabel(text)
    result.setTextFormat(Qt.TextFormat.PlainText)
    result.setWordWrap(True)
    if kind:
        result.setObjectName(kind)
    return result


def button(text: str, callback: Any, primary: bool = False) -> QPushButton:
    """Create a labeled action with an optional primary emphasis."""
    result = QPushButton(text)
    if primary:
        result.setObjectName("primary")
    result.clicked.connect(callback)
    return result


def checkbox(text: str) -> QCheckBox:
    """Build a high-contrast checkbox for the dark desktop theme."""
    return StyledCheckBox(text)


def combo(items: list[tuple[str, Any]]) -> QComboBox:
    """Build a selector with stable data values independent of translated labels."""
    result = QComboBox()
    # Qt renders the list inside a separate popup container. It does not inherit
    # the parent window's stylesheet, which otherwise leaves its top and bottom
    # margins in the platform default (white on common Linux themes).
    result.view().window().setStyleSheet(COMBO_POPUP_STYLESHEET)
    for text, value in items:
        result.addItem(text, value)
    return result


class ContentTabs(QTabWidget):
    """Size the active page without reserving space for a taller hidden tab."""

    def __init__(self) -> None:
        super().__init__()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        self.currentChanged.connect(self.fit_current_page)

    def fit_current_page(self) -> None:
        """Release the hidden page's cached minimum height after a tab change."""
        self.setMinimumHeight(self.minimumSizeHint().height())
        self.updateGeometry()

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt override
        """Return the active content's minimum dimensions plus its tab bar."""
        content = self.currentWidget()
        if content is None:
            return super().minimumSizeHint()
        size = content.minimumSizeHint()
        return QSize(size.width() + 4, size.height() + self.tabBar().sizeHint().height() + 4)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt override
        """Use the active page's preferred height."""
        content = self.currentWidget()
        if content is None:
            return super().sizeHint()
        size = content.sizeHint()
        return QSize(size.width() + 4, size.height() + self.tabBar().sizeHint().height() + 4)

    def heightForWidth(self, width: int) -> int:  # noqa: N802 - Qt override
        """Measure wrapped labels on the active page, excluding hidden pages."""
        content = self.currentWidget()
        if content is None or content.layout() is None:
            return super().heightForWidth(width)
        height = content.layout().totalHeightForWidth(max(0, width - 4))
        if height < 0:
            height = content.minimumSizeHint().height()
        return height + self.tabBar().sizeHint().height() + 4


class CsvFormatEditor(QWidget):
    """Optional dialect controls backed by the exporter's format validation."""

    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._updating = False
        self.source_format = CsvFormat()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.summary = label("", "muted")
        header = QHBoxLayout()
        header.addWidget(label("CSV-Format"))
        header.addStretch()
        self.toggle = button("Format anpassen", self._toggle)
        header.addWidget(self.toggle)
        layout.addLayout(header)
        layout.addWidget(self.summary)
        self.options = QWidget()
        form = QVBoxLayout(self.options)
        form.setContentsMargins(0, 12, 0, 0)
        form.setSpacing(14)
        self.encoding = combo(
            [
                ("UTF-8", "utf-8"),
                ("UTF-16 LE", "utf-16-le"),
                ("UTF-16 BE", "utf-16-be"),
                ("Windows-1252", "cp1252"),
                ("ISO-8859-1", "iso8859-1"),
            ]
        )
        self.delimiter = combo(
            [
                ("Semikolon (;)", ";"),
                ("Komma (,)", ","),
                ("Tabulator", "\t"),
                ("Leerzeichen", " "),
                ("Senkrechter Strich (|)", "|"),
                ("Eigenes Zeichen", None),
            ]
        )
        self.custom = QLineEdit()
        self.custom.setPlaceholderText("Genau ein Zeichen, z. B. ^")
        fields = QGridLayout()
        fields.setHorizontalSpacing(24)
        for column, (title, field) in enumerate(
            (("Zeichenkodierung", self.encoding), ("Trennzeichen", self.delimiter))
        ):
            fields.addWidget(label(title), 0, column)
            fields.addWidget(field, 1, column)
            fields.setColumnStretch(column, 1)
        form.addLayout(fields)
        self.custom_field = QWidget()
        custom_layout = QFormLayout(self.custom_field)
        custom_layout.setContentsMargins(0, 0, 0, 0)
        custom_layout.addRow("Eigenes Trennzeichen", self.custom)
        form.addWidget(self.custom_field)
        self.advanced_toggle = button("Weitere CSV-Details", self._toggle_advanced)
        self.advanced_toggle.setObjectName("quiet")
        form.addWidget(self.advanced_toggle)
        self.advanced = QWidget()
        advanced = QGridLayout(self.advanced)
        advanced.setHorizontalSpacing(24)
        advanced.setContentsMargins(0, 0, 0, 0)
        self.newline = combo(
            [("Windows (CRLF)", "\r\n"), ("Unix / Linux (LF)", "\n"), ("CR", "\r")]
        )
        self.quote = combo(
            [('Doppelte Anführungszeichen (")', '"'), ("Einfache Anführungszeichen (')", "'")]
        )
        self.quoting = combo([("Nur wenn nötig", "minimal"), ("Alle Felder", "all")])
        self.escape = combo(
            [("Anführungszeichen verdoppeln", True), ("Mit Backslash maskieren", False)]
        )
        self.bom = checkbox("Kodierungsmarkierung (BOM) schreiben")
        self.header = checkbox("Spaltennamen in erster Zeile ausgeben")
        for index, (title, widget) in enumerate(
            (
                ("Zeilenende", self.newline),
                ("Textbegrenzung", self.quote),
                ("Anführungszeichen", self.quoting),
                ("Maskierung", self.escape),
            )
        ):
            row, column = 2 * (index // 2), index % 2
            advanced.addWidget(label(title), row, column)
            advanced.addWidget(widget, row + 1, column)
            advanced.setColumnStretch(column, 1)
        advanced.addWidget(self.bom, 4, 0, 1, 2)
        advanced.addWidget(self.header, 5, 0, 1, 2)
        form.addWidget(self.advanced)
        self.remember = checkbox("Dieses Format für weitere Exporte merken")
        form.addWidget(self.remember)
        restore = button("Quellformat übernehmen", lambda: self.set_format(self.source_format))
        restore.setObjectName("quiet")
        form.addWidget(restore)
        layout.addWidget(self.options)
        self.options.hide()
        self.advanced.hide()
        self.encoding.currentIndexChanged.connect(self._encoding_changed)
        for widget in (self.delimiter, self.newline, self.quote, self.quoting, self.escape):
            widget.currentIndexChanged.connect(self._changed)
        self.custom.textChanged.connect(self._changed)
        self.bom.toggled.connect(self._changed)
        self.header.toggled.connect(self._changed)
        self.set_format(CsvFormat())

    def _toggle(self) -> None:
        self.options.setVisible(self.options.isHidden())
        self.toggle.setText(
            "Optionen schließen" if not self.options.isHidden() else "Format anpassen"
        )

    def _toggle_advanced(self) -> None:
        self.advanced.setVisible(self.advanced.isHidden())

    def _encoding_changed(self) -> None:
        if not self._updating:
            self.bom.setChecked(self.encoding.currentData().startswith("utf-16"))
        self._changed()

    def _changed(self) -> None:
        if self._updating:
            return
        self.custom_field.setVisible(self.delimiter.currentData() is None)
        self.bom.setVisible(self.encoding.currentData().startswith("utf-"))
        try:
            format_ = self.value()
            delimiter = {"\t": "Tabulator", " ": "Leerzeichen"}.get(
                format_.delimiter, format_.delimiter
            )
            newline = {"\r\n": "CRLF", "\n": "LF", "\r": "CR"}[format_.lineterminator]
            self.summary.setText(
                f"{self.encoding.currentText()}{' mit BOM' if format_.bom else ''} · "
                f"{delimiter} · {newline}"
            )
        except Exception as exc:
            self.summary.setText(str(exc))
        self.changed.emit()

    def value(self) -> CsvFormat:
        """Return validated export settings, raising on invalid combinations."""
        return CsvFormat(
            encoding=self.encoding.currentData(),
            delimiter=self.delimiter.currentData()
            if self.delimiter.currentData() is not None
            else self.custom.text(),
            bom=self.bom.isChecked() and self.encoding.currentData().startswith("utf-"),
            lineterminator=self.newline.currentData(),
            quotechar=self.quote.currentData(),
            quoting=self.quoting.currentData(),
            doublequote=self.escape.currentData(),
            header=self.header.isChecked(),
        )

    def set_format(self, format_: CsvFormat) -> None:
        """Populate controls without emitting intermediate invalid configurations."""
        self._updating = True
        for widget, value in (
            (self.encoding, format_.encoding),
            (self.newline, format_.lineterminator),
            (self.quote, format_.quotechar),
            (self.quoting, format_.quoting),
            (self.escape, format_.doublequote),
        ):
            widget.setCurrentIndex(widget.findData(value))
        index = self.delimiter.findData(format_.delimiter)
        self.delimiter.setCurrentIndex(index if index >= 0 else self.delimiter.count() - 1)
        self.custom.setText(format_.delimiter if index < 0 else "")
        self.bom.setChecked(format_.bom)
        self.header.setChecked(format_.header)
        self._updating = False
        self._changed()
