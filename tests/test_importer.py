"""Tests for the CSV importer (``pdo.core.importer``)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from pdo.core.db import Database
from pdo.core.importer import ColumnMapping, import_csv
from pdo.exceptions import ImportDataError


@pytest.fixture()
def db() -> Iterator[Database]:
    with Database(":memory:") as database:
        database.initialize()
        yield database


def _write_csv(path: Path, content: str) -> Path:
    """Write CSV content to a file and return the path."""
    path.write_text(content, encoding="utf-8")
    return path


BASIC_CSV = (
    '"ProductID";"Title";"Description";"Brand"\n'
    '"P001";"Widget A";"A fine widget";"BrandX"\n'
    '"P002";"Widget B";"A better widget";"BrandY"\n'
    '"P003";"Widget C";"The best widget";"BrandZ"\n'
)

BASIC_MAPPINGS = [
    ColumnMapping(role="product_id", csv_column_name="ProductID"),
    ColumnMapping(role="description", csv_column_name="Description"),
    ColumnMapping(role="context", csv_column_name="Brand"),
    ColumnMapping(role="context", csv_column_name="Title"),
]


class TestImportValid:
    def test_imports_all_rows(self, db: Database, tmp_path: Path) -> None:
        csv_file = _write_csv(tmp_path / "products.csv", BASIC_CSV)
        result = import_csv(db, csv_file, column_mappings=BASIC_MAPPINGS)
        assert result.imported_count == 3
        assert result.total_rows == 3
        assert result.skipped_count == 0
        assert result.errors == []

    def test_import_with_limit(self, db: Database, tmp_path: Path) -> None:
        csv_file = _write_csv(tmp_path / "products.csv", BASIC_CSV)
        result = import_csv(db, csv_file, column_mappings=BASIC_MAPPINGS, limit=2)
        assert result.imported_count == 2
        assert result.total_rows == 2
        assert result.skipped_count == 0
        assert result.errors == []
        products = db.get_all_products()
        assert len(products) == 2
        assert products[0]["product_id_value"] == "P001"
        assert products[1]["product_id_value"] == "P002"

    def test_products_in_database(self, db: Database, tmp_path: Path) -> None:
        csv_file = _write_csv(tmp_path / "products.csv", BASIC_CSV)
        import_csv(db, csv_file, column_mappings=BASIC_MAPPINGS)
        products = db.get_all_products()
        assert len(products) == 3
        assert all(p["status"] == "pending" for p in products)

    def test_product_id_extracted(self, db: Database, tmp_path: Path) -> None:
        csv_file = _write_csv(tmp_path / "products.csv", BASIC_CSV)
        import_csv(db, csv_file, column_mappings=BASIC_MAPPINGS)
        products = db.get_all_products()
        assert products[0]["product_id_value"] == "P001"

    def test_description_extracted(self, db: Database, tmp_path: Path) -> None:
        csv_file = _write_csv(tmp_path / "products.csv", BASIC_CSV)
        import_csv(db, csv_file, column_mappings=BASIC_MAPPINGS)
        products = db.get_all_products()
        assert products[0]["original_description"] == "A fine widget"

    def test_context_data_extracted(self, db: Database, tmp_path: Path) -> None:
        csv_file = _write_csv(tmp_path / "products.csv", BASIC_CSV)
        import_csv(db, csv_file, column_mappings=BASIC_MAPPINGS)
        products = db.get_all_products()
        ctx = products[0]["context_data"]
        assert ctx["Brand"] == "BrandX"
        assert ctx["Title"] == "Widget A"

    def test_raw_data_preserved(self, db: Database, tmp_path: Path) -> None:
        csv_file = _write_csv(tmp_path / "products.csv", BASIC_CSV)
        import_csv(db, csv_file, column_mappings=BASIC_MAPPINGS)
        products = db.get_all_products()
        raw = products[0]["raw_data"]
        assert raw["ProductID"] == "P001"
        assert raw["Description"] == "A fine widget"

    def test_column_mappings_persisted(self, db: Database, tmp_path: Path) -> None:
        csv_file = _write_csv(tmp_path / "products.csv", BASIC_CSV)
        import_csv(db, csv_file, column_mappings=BASIC_MAPPINGS)
        mappings = db.get_column_mappings()
        assert len(mappings) == 4
        roles = {m["role"] for m in mappings}
        assert roles == {"product_id", "description", "context"}


class TestImportErrors:
    def test_file_not_found(self, db: Database, tmp_path: Path) -> None:
        with pytest.raises(ImportDataError, match="not found"):
            import_csv(
                db,
                tmp_path / "nonexistent.csv",
                column_mappings=BASIC_MAPPINGS,
            )

    def test_empty_file(self, db: Database, tmp_path: Path) -> None:
        csv_file = _write_csv(tmp_path / "empty.csv", "")
        with pytest.raises(ImportDataError, match="empty"):
            import_csv(db, csv_file, column_mappings=BASIC_MAPPINGS)

    def test_missing_description_mapping(self, db: Database, tmp_path: Path) -> None:
        csv_file = _write_csv(tmp_path / "products.csv", BASIC_CSV)
        mappings = [ColumnMapping(role="product_id", csv_column_name="ProductID")]
        with pytest.raises(ImportDataError, match="description"):
            import_csv(db, csv_file, column_mappings=mappings)

    def test_missing_csv_column(self, db: Database, tmp_path: Path) -> None:
        csv_file = _write_csv(tmp_path / "products.csv", BASIC_CSV)
        mappings = [
            ColumnMapping(role="description", csv_column_name="Description"),
            ColumnMapping(role="context", csv_column_name="NonexistentColumn"),
        ]
        with pytest.raises(ImportDataError, match="NonexistentColumn"):
            import_csv(db, csv_file, column_mappings=mappings)


class TestImportSpecialCases:
    def test_utf8_bom_header(self, db: Database, tmp_path: Path) -> None:
        csv_file = _write_csv(
            tmp_path / "bom.csv", '\ufeff"ProductID";"Description"\n"P001";"Text"\n'
        )
        mappings = [ColumnMapping(role="description", csv_column_name="Description")]
        result = import_csv(db, csv_file, column_mappings=mappings)
        assert result.imported_count == 1
        assert db.get_all_products()[0]["original_description"] == "Text"

    def test_imports_multiple_batches(self, db: Database, tmp_path: Path) -> None:
        lines = ["ProductID;Description"] + [f"P{i:04};Text {i}" for i in range(1001)]
        csv_file = _write_csv(tmp_path / "large.csv", "\n".join(lines) + "\n")
        mappings = [ColumnMapping(role="description", csv_column_name="Description")]
        result = import_csv(db, csv_file, column_mappings=mappings)
        assert result.imported_count == 1001
        assert db.get_progress()["total"] == 1001

    def test_unicode_content(self, db: Database, tmp_path: Path) -> None:
        csv_content = (
            '"ProductID";"Description"\n'
            '"P001";"Oil paint — premium quality for artists"\n'
            '"P002";"Size: 50x70 cm, thickness: 3 mm"\n'
        )
        csv_file = _write_csv(tmp_path / "unicode.csv", csv_content)
        mappings = [
            ColumnMapping(role="description", csv_column_name="Description"),
            ColumnMapping(role="product_id", csv_column_name="ProductID"),
        ]
        result = import_csv(db, csv_file, column_mappings=mappings)
        assert result.imported_count == 2
        products = db.get_all_products()
        assert "Oil paint" in products[0]["original_description"]

    def test_empty_description(self, db: Database, tmp_path: Path) -> None:
        csv_content = '"ProductID";"Description"\n"P001";""\n'
        csv_file = _write_csv(tmp_path / "empty_desc.csv", csv_content)
        mappings = [
            ColumnMapping(role="description", csv_column_name="Description"),
        ]
        result = import_csv(db, csv_file, column_mappings=mappings)
        assert result.imported_count == 1
        product = db.get_all_products()[0]
        assert product["original_description"] == ""

    def test_pipeline_state_returns_to_idle(self, db: Database, tmp_path: Path) -> None:
        csv_file = _write_csv(tmp_path / "products.csv", BASIC_CSV)
        import_csv(db, csv_file, column_mappings=BASIC_MAPPINGS)
        state = db.get_pipeline_state()
        assert state["stage"] == "idle"
        assert state["total_products"] == 3
