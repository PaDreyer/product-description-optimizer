"""Desktop workflow tests using temporary data and the demo optimizer."""

from __future__ import annotations

import csv
import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from pdo.config import PdoConfig, load_config, save_config_values
from pdo.core.db import Database
from pdo.desktop.session import DesktopSession, inspect_csv, suggest_role
from pdo.exceptions import InstanceAlreadyRunningError


def _wait_for_job(session: DesktopSession) -> None:
    deadline = time.monotonic() + 5
    while session.worker.is_busy and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not session.worker.is_busy


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
    config = PdoConfig(data_dir=tmp_path / "data", config_file_path=tmp_path / "config.toml")
    session = DesktopSession(config)
    try:
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
    finally:
        session.close()


def test_desktop_session_recovers_interrupted_product(tmp_path: Path) -> None:
    config = PdoConfig(data_dir=tmp_path / "data", config_file_path=tmp_path / "config.toml")
    config.data_dir.mkdir()
    with Database(config.data_dir / "pdo.db") as db:
        db.initialize()
        db.insert_products([{"source_row_number": 1, "raw_data": {}, "product_id_value": "A1"}])
        db.update_product_status(1, "processing")
        db.set_pipeline_state("optimizing")
    session = DesktopSession(config)
    try:
        assert session.status()["progress"]["pending"] == 1
        assert session.status()["stage"] == "idle"
    finally:
        session.close()


def test_desktop_session_excludes_second_process(tmp_path: Path) -> None:
    config = PdoConfig(data_dir=tmp_path / "data", config_file_path=tmp_path / "config.toml")
    session = DesktopSession(config)
    try:
        with pytest.raises(InstanceAlreadyRunningError):
            DesktopSession(config)
    finally:
        session.close()


def test_failed_replacement_import_preserves_current_batch(tmp_path: Path) -> None:
    config = PdoConfig(data_dir=tmp_path / "data", config_file_path=tmp_path / "config.toml")
    session = DesktopSession(config)
    try:
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
    finally:
        session.close()


def test_desktop_window_runs_guided_workflow_offscreen(tmp_path: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from pdo.desktop.app import DesktopWindow

    app = QApplication.instance() or QApplication([])
    config = PdoConfig(data_dir=tmp_path / "data", config_file_path=tmp_path / "config.toml")
    window = DesktopWindow(DesktopSession(config))
    try:
        assert window.windowTitle().startswith("PDO")
        assert window.pages.count() == 4

        source = tmp_path / "products.csv"
        source.write_text("SKU,Description,Brand\nA1,Blue bag,Example\n", encoding="utf-8")
        with patch(
            "pdo.desktop.app.QFileDialog.getOpenFileName",
            return_value=(str(source), "CSV-Dateien (*.csv)"),
        ):
            window._choose_source()
        assert window.sample_table.rowCount() == 1
        assert len(window._mapping_boxes) == 3

        for backend, expected_text in (
            ("gemini", "Cloud-Anbieter"),
            ("local_llm", "Server-Adresse"),
            ("dummy", "direkt auf diesem Computer"),
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
        window.close()
