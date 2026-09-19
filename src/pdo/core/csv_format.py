from __future__ import annotations

__doc__ = """CSV dialects shared by import, export, preview, and desktop settings."""

import codecs
import csv
import io
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from pdo.exceptions import ExportError, ImportDataError


@dataclass(frozen=True)
class CsvFormat:
    """Serializable CSV format; Unicode byte order and BOM are explicit."""

    encoding: str = "utf-8"
    delimiter: str = ";"
    bom: bool = False
    lineterminator: str = "\r\n"
    quotechar: str = '"'
    quoting: str = "minimal"
    doublequote: bool = True
    header: bool = True

    def __post_init__(self) -> None:
        if self.encoding not in {"utf-8", "utf-16-le", "utf-16-be", "cp1252", "iso8859-1"}:
            raise ExportError("Nicht unterstützte Zeichenkodierung.")
        for value in (self.delimiter, self.quotechar):
            if not isinstance(value, str) or len(value) != 1 or value in "\r\n\0":
                raise ExportError("Trenn- und Textbegrenzungszeichen müssen einzelne Zeichen sein.")
        if self.delimiter == self.quotechar:
            raise ExportError("Trennzeichen und Textbegrenzungszeichen müssen verschieden sein.")
        if not self.doublequote and "\\" in (self.delimiter, self.quotechar):
            raise ExportError("Backslash ist bereits als Maskierungszeichen belegt.")
        if self.lineterminator not in {"\r\n", "\n", "\r"}:
            raise ExportError("Ungültiges Zeilenende.")
        if self.quoting not in {"minimal", "all"}:
            raise ExportError("Ungültige Anführungszeichen-Einstellung.")
        if any(type(value) is not bool for value in (self.bom, self.doublequote, self.header)):
            raise ExportError("CSV-Schalter müssen boolesche Werte sein.")
        if self.bom and not self.encoding.startswith("utf-"):
            raise ExportError("BOM ist nur für Unicode-Kodierungen verfügbar.")

    def to_dict(self) -> dict[str, Any]:
        """Return serializable format settings."""
        return asdict(self)

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> CsvFormat:
        """Validate settings received from configuration or IPC."""
        try:
            return cls(**values)
        except (TypeError, ValueError) as exc:
            raise ExportError(f"Ungültiges CSV-Format: {exc}") from exc

    def writer_kwargs(self) -> dict[str, Any]:
        """Return arguments shared by real exports and their previews."""
        return {
            "delimiter": self.delimiter,
            "quotechar": self.quotechar,
            "quoting": csv.QUOTE_ALL if self.quoting == "all" else csv.QUOTE_MINIMAL,
            "doublequote": self.doublequote,
            "escapechar": None if self.doublequote else "\\",
            "lineterminator": self.lineterminator,
        }

    def reader_kwargs(self) -> dict[str, Any]:
        """Return the corresponding parser options."""
        return {
            key: value for key, value in self.writer_kwargs().items() if key != "lineterminator"
        }


def detect_format(path: Path) -> CsvFormat:
    """Detect encoding and dialect without loading an entire CSV into memory.

    Args:
        path: Existing CSV source.

    Returns:
        Detected dialect, including byte order, BOM, and line endings.

    Raises:
        ImportDataError: If the file is empty or unreadable.
    """
    try:
        with path.open("rb") as stream:
            sample = stream.read(64 * 1024)
        if not sample:
            raise ImportDataError("Die CSV-Datei ist leer.")
        encoding, bom = "utf-8", False
        for marker, candidate in (
            (codecs.BOM_UTF8, "utf-8"),
            (codecs.BOM_UTF16_LE, "utf-16-le"),
            (codecs.BOM_UTF16_BE, "utf-16-be"),
        ):
            if sample.startswith(marker):
                encoding, bom = candidate, True
                break
        else:
            if sample[1::2].count(0) > len(sample) // 8:
                encoding = "utf-16-le"
            elif sample[::2].count(0) > len(sample) // 8:
                encoding = "utf-16-be"
            else:
                try:
                    with path.open(encoding="utf-8") as stream:
                        while stream.read(64 * 1024):
                            pass
                except UnicodeDecodeError:
                    encoding = "cp1252"
        with path.open(encoding=encoding, newline="") as stream:
            text = stream.read(8192).lstrip("\ufeff")
        if not text.strip():
            raise ImportDataError("Die CSV-Datei ist leer.")
        delimiter, quotechar = ";", '"'
        # Spaces inside quoted descriptions can mislead Sniffer's quote heuristic.
        # Prefer punctuation separators, and require a matching multi-column header.
        for candidates in (";,\t|", " "):
            try:
                dialect = csv.Sniffer().sniff(text, delimiters=candidates)
                header = next(csv.reader(io.StringIO(text), dialect), [])
                if len(header) > 1:
                    delimiter, quotechar = dialect.delimiter, dialect.quotechar
                    break
            except csv.Error:
                continue
        newline = "\r\n" if "\r\n" in text else "\n" if "\n" in text else "\r"
        return CsvFormat(encoding, delimiter, bom, newline, quotechar)
    except (OSError, UnicodeError) as exc:
        raise ImportDataError(f"CSV konnte nicht gelesen werden: {exc}") from exc


def read_encoding(format_: CsvFormat) -> str:
    """Return a decoding codec that consumes the optional BOM."""
    if format_.bom:
        return "utf-8-sig" if format_.encoding == "utf-8" else "utf-16"
    return format_.encoding
