from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import Workbook

from app.api import compat_knowledge
from app.framework.config import DEFAULT_JWT_SECRET, Settings, validate_jwt_secret
from app.framework.errors import AppError
from app.modules.knowledge.service import DocumentParser
from app.modules.knowledge.uploads import validate_upload


def _write_xlsx(path: Path) -> None:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "商品"
    worksheet.append(["名称", "说明"])
    worksheet.append(["咖啡", "可退货"])
    workbook.save(path)


def test_production_jwt_secret_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("JWT_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        Settings()

    monkeypatch.setenv("JWT_SECRET", DEFAULT_JWT_SECRET)
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        validate_jwt_secret("prod")

    monkeypatch.setenv("JWT_SECRET", "REPLACE_WITH_RANDOM_64_CHAR_SECRET")
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        validate_jwt_secret("production")


def test_production_jwt_secret_accepts_strong_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "q7!A-long-production-secret-2026-安全"
    monkeypatch.setenv("JWT_SECRET", secret)
    monkeypatch.setenv("APP_ENV", "prod")
    assert validate_jwt_secret("production") == secret
    assert Settings().environment == "prod"


def test_document_parser_reads_csv_and_xlsx(tmp_path: Path) -> None:
    csv_path = tmp_path / "catalog.csv"
    csv_path.write_text("名称,说明\n咖啡,可退货\n", encoding="utf-8")
    xlsx_path = tmp_path / "catalog.xlsx"
    _write_xlsx(xlsx_path)

    csv_text = DocumentParser().parse(csv_path)
    xlsx_text = DocumentParser().parse(xlsx_path)
    assert "咖啡" in csv_text and "可退货" in csv_text
    assert "[工作表: 商品]" in xlsx_text
    assert "咖啡" in xlsx_text and "可退货" in xlsx_text
    assert validate_upload(type("Upload", (), {"filename": "catalog.csv"})()) == "catalog.csv"
    assert validate_upload(type("Upload", (), {"filename": "catalog.xlsx"})()) == "catalog.xlsx"


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"max_rows": 1}, "DOCUMENT_ROWS_TOO_LARGE"),
        ({"max_columns": 1}, "DOCUMENT_COLUMNS_TOO_LARGE"),
        ({"max_cell_chars": 2}, "DOCUMENT_CELL_TOO_LARGE"),
        ({"max_text_chars": 3}, "DOCUMENT_TEXT_TOO_LARGE"),
    ],
)
def test_document_parser_enforces_spreadsheet_limits(
    tmp_path: Path, kwargs: dict, code: str
) -> None:
    csv_path = tmp_path / "large.csv"
    csv_path.write_text("name,description\ncoffee,returnable\n", encoding="utf-8")
    with pytest.raises(AppError) as error:
        DocumentParser(**kwargs).parse(csv_path)
    assert error.value.code == code
    assert error.value.status_code == 413


def test_compat_preview_uses_binary_parser_for_xlsx(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    xlsx_path = tmp_path / "preview.xlsx"
    _write_xlsx(xlsx_path)
    document = type("Document", (), {"storage_path": str(xlsx_path)})()
    monkeypatch.setattr(compat_knowledge, "_resolve_document", lambda *_: document)

    response = compat_knowledge.preview_document(1, object(), object(), object())

    assert response.data is not None
    assert "咖啡" in response.data
    assert "可退货" in response.data


def test_compat_preview_truncates_large_text_without_parse_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    text_path = tmp_path / "long.txt"
    text_path.write_text("知识库内容。" * 4_000, encoding="utf-8")
    document = type("Document", (), {"storage_path": str(text_path)})()
    monkeypatch.setattr(compat_knowledge, "_resolve_document", lambda *_: document)

    response = compat_knowledge.preview_document(1, object(), object(), object())

    assert response.data is not None
    assert len(response.data) == 20_000


def test_application_lifespan_disposes_rebuilt_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.application_core as core

    monkeypatch.setenv("APP_ENV", "development")

    class Engine:
        def __init__(self) -> None:
            self.dispose_count = 0

        def dispose(self) -> None:
            self.dispose_count += 1

    class Database:
        def __init__(self) -> None:
            self.engine = Engine()

    class Container:
        def __init__(self) -> None:
            self.database = Database()

    first, rebuilt = Container(), Container()
    containers = iter((first, rebuilt))
    monkeypatch.setattr(core, "build_container", lambda _: next(containers))
    monkeypatch.setattr(core, "upgrade_database", lambda _: None)
    monkeypatch.setattr(core, "apply_restart_env_overrides", lambda _: True)

    app = core.create_app(Settings())
    async def exercise() -> None:
        async with app.router.lifespan_context(app):
            assert app.state.container is rebuilt

    import asyncio

    asyncio.run(exercise())
    assert first.database.engine.dispose_count == 1
    assert rebuilt.database.engine.dispose_count == 1
