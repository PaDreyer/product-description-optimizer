from __future__ import annotations

__doc__ = "Regression tests for large batches, safe correction imports, and CSV dialects."

import codecs
import csv
import io
import json
import sqlite3
import threading
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pdo.config import PdoConfig
from pdo.core.csv_format import CsvFormat, detect_format, read_encoding
from pdo.core.db import Database
from pdo.core.error_groups import classify_error
from pdo.core.exporter import export_csv, preview_csv
from pdo.core.importer import ColumnMapping, import_corrections, import_csv
from pdo.core.model_discovery import discover_models
from pdo.core.optimizer import DummyOptimizer, run_optimization
from pdo.daemon.worker import Worker
from pdo.exceptions import ConfigError, ExportError, ImportDataError


@pytest.fixture()
def db() -> Iterator[Database]:
    """Return an isolated database with source columns and column assignments."""
    with Database(":memory:") as database:
        database.initialize()
        database.set_metadata("source_headers", ["SKU", "Beschreibung"])
        database.set_column_mappings(
            [
                {"role": "product_id", "csv_column_name": "SKU", "display_name": "SKU"},
                {
                    "role": "description",
                    "csv_column_name": "Beschreibung",
                    "display_name": "Beschreibung",
                },
            ]
        )
        yield database


def _products(count: int, description: str = 'Größe L, blau; "weich"\nzweite Zeile') -> list[dict]:
    return [
        {
            "source_row_number": i,
            "product_id_value": f"P{i}",
            "raw_data": {"SKU": f"P{i}", "Beschreibung": description},
            "original_description": description,
            "context_data": None,
        }
        for i in range(1, count + 1)
    ]


@pytest.mark.parametrize(
    ("encoding", "bom"),
    [
        ("utf-8", False),
        ("utf-8", True),
        ("utf-16-le", True),
        ("utf-16-be", True),
        ("utf-16-le", False),
        ("utf-16-be", False),
        ("cp1252", False),
        ("iso8859-1", False),
    ],
)
@pytest.mark.parametrize("delimiter", [";", ",", "\t", " ", "|"])
def test_export_preserves_text_in_each_supported_encoding_and_separator(
    db: Database, tmp_path: Path, encoding: str, bom: bool, delimiter: str
) -> None:
    db.insert_products(_products(1))
    run_optimization(db, DummyOptimizer())
    format_ = CsvFormat(encoding=encoding, delimiter=delimiter, bom=bom)
    output = tmp_path / "output.csv"
    assert export_csv(db, output, format_=format_).total_exported == 1
    data = output.read_bytes()
    markers = {
        "utf-8": codecs.BOM_UTF8,
        "utf-16-le": codecs.BOM_UTF16_LE,
        "utf-16-be": codecs.BOM_UTF16_BE,
    }
    if encoding in markers:
        assert data.startswith(markers[encoding]) is bom
    text = data.decode(read_encoding(format_))
    assert text == preview_csv(db, format_)
    row = next(csv.DictReader(io.StringIO(text, newline=""), **format_.reader_kwargs()))
    assert row["Beschreibung"] == _products(1)[0]["original_description"]
    assert row["optimized_description"].startswith("[OPTIMIZED]")
    assert row["status"] == "done"


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
@pytest.mark.parametrize("doublequote", [True, False])
@pytest.mark.parametrize("header", [True, False])
def test_custom_dialect_quotes_and_headers_roundtrip(
    db: Database, tmp_path: Path, newline: str, doublequote: bool, header: bool
) -> None:
    db.insert_products(_products(1, "Text 'zitiert' ^ Backslash \\"))
    run_optimization(db, DummyOptimizer())
    format_ = CsvFormat(
        delimiter="^",
        quotechar="'",
        quoting="all",
        doublequote=doublequote,
        lineterminator=newline,
        header=header,
    )
    output = tmp_path / "custom.csv"
    export_csv(db, output, format_=format_)
    text = output.read_bytes().decode()
    assert text.endswith(newline)
    rows = list(csv.reader(io.StringIO(text, newline=""), **format_.reader_kwargs()))
    assert len(rows) == (2 if header else 1)
    assert rows[-1][1] == "Text 'zitiert' ^ Backslash \\"
    assert text == preview_csv(db, format_)


@pytest.mark.parametrize(
    "values",
    [
        {"delimiter": ""},
        {"delimiter": ",,"},
        {"delimiter": "\n"},
        {"delimiter": '"'},
        {"encoding": "unknown"},
        {"encoding": "cp1252", "bom": True},
        {"bom": "true"},
        {"quoting": "none"},
        {"lineterminator": "x"},
        {"surprise": True},
        {"doublequote": False, "delimiter": "\\"},
    ],
)
def test_invalid_formats_rejected(values: dict) -> None:
    with pytest.raises(ExportError):
        CsvFormat.from_dict(values)


def test_unrepresentable_late_row_keeps_existing_output_intact(
    db: Database, tmp_path: Path
) -> None:
    products = _products(501)
    products[-1]["raw_data"]["Beschreibung"] = "Unicode 😀"
    db.insert_products(products)
    output = tmp_path / "existing.csv"
    output.write_text("Existing export", encoding="utf-8")
    with pytest.raises(ExportError):
        export_csv(db, output, scope="all", format_=CsvFormat(encoding="cp1252"))
    assert output.read_text() == "Existing export"
    assert not list(tmp_path.glob(".pdo-export-*"))
    assert db.get_pipeline_state()["stage"] == "idle"


def test_source_file_cannot_be_overwritten(db: Database, tmp_path: Path) -> None:
    source = tmp_path / "source.csv"
    source.write_text("Original", encoding="utf-8")
    db.insert_products(_products(1))
    db.set_pipeline_state("idle", source_file=str(source))
    with pytest.raises(ExportError, match="Quelldatei"):
        export_csv(db, source, scope="all")
    assert source.read_text() == "Original"


def test_existing_status_and_result_columns_are_preserved(db: Database, tmp_path: Path) -> None:
    products = _products(1)
    products[0]["raw_data"].update(
        {"status": "active", "pdo_status": "existing", "optimized_description": "Older text"}
    )
    db.set_metadata("source_headers", list(products[0]["raw_data"]))
    db.insert_products(products)
    run_optimization(db, DummyOptimizer())
    output = tmp_path / "result.csv"
    export_csv(db, output)
    with output.open(newline="") as stream:
        row = next(csv.DictReader(stream, delimiter=";"))
    assert row["status"] == "active"
    assert row["pdo_status"] == "existing"
    assert row["pdo_status_2"] == "done"
    assert row["optimized_description"] == "Older text"
    assert row["pdo_optimized_description"].startswith("[OPTIMIZED]")
    assert (
        preview_csv(db, CsvFormat())
        .splitlines()[0]
        .endswith("pdo_optimized_description;pdo_status_2")
    )


@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-16", "utf-16-be", "cp1252"])
def test_import_detects_encoding_delimiter_and_source_format(tmp_path: Path, encoding: str) -> None:
    source = tmp_path / "source.csv"
    source.write_bytes("SKU,Beschreibung\r\nP1,Größe L\r\n".encode(encoding))
    format_ = detect_format(source)
    assert format_.delimiter == ","
    assert format_.lineterminator == "\r\n"
    with Database(":memory:") as database:
        database.initialize()
        result = import_csv(
            database,
            source,
            column_mappings=[
                ColumnMapping("product_id", "SKU", "SKU"),
                ColumnMapping("description", "Beschreibung", "Beschreibung"),
            ],
            format_=format_,
        )
        assert result.imported_count == 1
        assert database.get_product(1)["original_description"] == "Größe L"
        assert database.get_metadata("source_format") == format_.to_dict()


def test_group_retry_covers_all_twenty_thousand_rows_but_preserves_other_work(db: Database) -> None:
    db.insert_products(_products(20_000, "Tasche"))
    with db._conn:
        db._conn.execute("UPDATE products SET status = 'done', optimized_description = 'Behalten'")
        db._conn.execute(
            "UPDATE products SET status = 'error', error_kind = 'timeout' WHERE id > 19000"
        )
        db._conn.execute("UPDATE products SET error_kind = 'connection' WHERE id > 19800")
        db._conn.execute("UPDATE products SET status = 'pending' WHERE id = 1")
    groups = {g["kind"]: g["count"] for g in db.get_error_groups()}
    assert groups == {"timeout": 800, "connection": 200}
    assert len(db.get_product_preview(limit=1000)) == 100
    assert db.get_product_preview(offset=19_900)[-1]["product_id_value"] == "P20000"
    ids = db.requeue_errors(["timeout"])
    assert len(ids) == 800
    run_optimization(db, DummyOptimizer(), product_ids=ids)
    assert db.get_product(1)["status"] == "pending"
    assert db.get_product(2)["optimized_description"] == "Behalten"
    assert db.get_product(19_001)["optimized_description"] == "[OPTIMIZED] TASCHE"
    assert db.get_product(20_000)["status"] == "error"
    assert db.count_products(status="error") == 200
    assert db.count_products(search="P20000") == 1
    assert db.get_product_preview(search="P20000")[0]["id"] == 20_000


def test_correction_csv_is_atomic_and_only_changes_uniquely_identified_errors(
    db: Database, tmp_path: Path
) -> None:
    db.insert_products(_products(3, ""))
    run_optimization(db, DummyOptimizer())
    db.update_product_status(3, "done", optimized_description="Bereits fertig")
    output = tmp_path / "corrections.csv"
    assert export_csv(db, output, scope="corrections").total_exported == 2
    assert output.read_text().splitlines()[0] == "SKU;Beschreibung"
    for invalid_id in ("P1", "P3", "P99", ""):
        output.write_text(f"SKU;Beschreibung\nP1;Korrigiert\n{invalid_id};Text\n", encoding="utf-8")
        with pytest.raises(ImportDataError):
            import_corrections(db, output, CsvFormat())
        assert db.get_product(1)["original_description"] == ""
        assert db.get_product(3)["optimized_description"] == "Bereits fertig"
    output.write_text("SKU;Beschreibung\nP1;Korrigiert\nP2;Ergänzt\n", encoding="utf-16")
    assert import_corrections(db, output, detect_format(output)) == 2
    assert db.get_error_groups()[0]["kind"] == "corrected"
    run_optimization(db, DummyOptimizer(), product_ids=db.requeue_errors(["corrected"]))
    assert db.get_progress()["done"] == 3
    assert db.get_product(3)["optimized_description"] == "Bereits fertig"
    assert db.get_product(1)["error_message"] is None


def test_legacy_database_migrates_error_groups_and_reset_clears_them(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    with Database(path) as database:
        database.initialize()
        database.insert_products(_products(1))
        database.update_product_status(1, "error", error_message="Connection timed out")
    with sqlite3.connect(path) as connection:
        connection.execute("ALTER TABLE products DROP COLUMN error_kind")
    with Database(path) as database:
        database.initialize()
        assert database.get_error_groups()[0]["kind"] == "timeout"
        database.reset(keep=True)
        assert database.get_product(1)["error_kind"] is None


@pytest.mark.parametrize(
    ("message", "kind"),
    [
        ("429 rate limit", "rate_limit"),
        ("401 unauthorized", "authentication"),
        ("API connection refused", "connection"),
        ("Read timed out", "timeout"),
        ("oops", "other"),
    ],
)
def test_provider_failure_categorization(message: str, kind: str) -> None:
    assert classify_error(RuntimeError(message)) == kind


def test_failed_provider_setup_does_not_requeue_errors(
    db: Database, test_config: PdoConfig
) -> None:
    db.insert_products(_products(1))
    db.update_product_status(1, "error", error_message="timeout")
    worker = Worker(db, test_config)
    with (
        patch("pdo.daemon.worker.create_optimizer", side_effect=ValueError("Invalid key")),
        pytest.raises(ValueError, match="Invalid key"),
    ):
        worker.start_optimization(retry_groups=["timeout"])
    assert db.get_product(1)["status"] == "error"


def test_selected_retry_throttle_can_be_stopped(db: Database) -> None:
    db.insert_products(_products(1))
    stop = threading.Event()
    with patch.object(stop, "wait", return_value=True) as wait:
        run_optimization(db, DummyOptimizer(), product_ids=[1], request_interval=1, stop_event=stop)
    wait.assert_called_once_with(1)
    assert db.get_product(1)["status"] == "pending"


def test_model_discovery_handles_one_or_multiple_models_without_manual_ids() -> None:
    response = MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps(
        {"data": [{"id": "loaded-model"}, {"id": "loaded-model"}, {"id": "second"}, {"id": 1}]}
    ).encode()
    with patch("pdo.core.model_discovery.urlopen", return_value=response) as request:
        assert discover_models("http://localhost:1234/v1/") == ["loaded-model", "second"]
    assert request.call_args.args[0].full_url == "http://localhost:1234/v1/models"
    assert request.call_args.kwargs["timeout"] == 3


@pytest.mark.parametrize(
    "address",
    ["file:///tmp/models", "localhost:1234", "http://a?key=x", "http://user:password@localhost/v1"],
)
def test_model_discovery_validates_address(address: str) -> None:
    with pytest.raises(ConfigError):
        discover_models(address)


@pytest.mark.parametrize("payload", [b"invalid", b"{}", b'{"data": []}', b"x" * 1_000_001])
def test_model_discovery_explains_invalid_or_empty_response(payload: bytes) -> None:
    response = MagicMock()
    response.__enter__.return_value.read.return_value = payload
    with (
        patch("pdo.core.model_discovery.urlopen", return_value=response),
        pytest.raises(ConfigError, match="Modellerkennung"),
    ):
        discover_models("http://localhost/v1")


@pytest.mark.parametrize("separator", [";", ",", "\t", " "])
def test_separator_detection_with_quoted_spaces_and_embedded_quotes(
    tmp_path: Path, separator: str
) -> None:
    source = tmp_path / "quoted.csv"
    with source.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, delimiter=separator)
        writer.writerow(["SKU", "Beschreibung"])
        writer.writerows((f"P{i}", f'Tasche Größe L, "blau" {i}') for i in range(300))
    assert detect_format(source).delimiter == separator
