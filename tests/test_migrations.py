from __future__ import annotations

import pytest
from sqlalchemy import inspect, text

from app.framework.database import Base, Database
from app.framework.migrations import upgrade_database

from app.modules.conversations import models as conversation_models  # noqa: F401,E402
from app.modules.knowledge import models as knowledge_models  # noqa: F401,E402
from app.modules.rag import trace_models as rag_trace_models  # noqa: F401,E402
from app.modules.users import models as user_models  # noqa: F401,E402


def test_upgrade_database_builds_empty_sqlite_schema(tmp_path):
    database = Database(f"sqlite:///{tmp_path / 'empty.db'}")

    upgrade_database(database)

    tables = set(inspect(database.engine).get_table_names())
    assert "alembic_version" in tables
    assert {"users_v2", "conversations", "messages", "knowledge_documents"} <= tables


def test_upgrade_database_adopts_current_pre_alembic_schema(tmp_path):
    database = Database(f"sqlite:///{tmp_path / 'legacy.db'}")
    Base.metadata.create_all(database.engine)
    with database.engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO users_v2 (
                    username, password_hash, email, is_active, role, created_at, updated_at
                ) VALUES (
                    'legacy-user', 'hash', NULL, 1, 'user',
                    '2026-08-07 00:00:00', '2026-08-07 00:00:00'
                )
                """
            )
        )

    upgrade_database(database)

    with database.engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT version_num FROM alembic_version"))
            == "0001_current_schema"
        )
        assert connection.scalar(text("SELECT username FROM users_v2")) == "legacy-user"


@pytest.mark.parametrize(
    "setup_sql",
    [
        "CREATE TABLE mystery_records (id INTEGER PRIMARY KEY, value TEXT)",
        "CREATE TABLE users_v2 (id INTEGER PRIMARY KEY, username VARCHAR(50))",
    ],
    ids=["unknown", "partial"],
)
def test_upgrade_database_rejects_unrecognized_pre_alembic_schema(tmp_path, setup_sql):
    database = Database(f"sqlite:///{tmp_path / 'unrecognized.db'}")
    with database.engine.begin() as connection:
        connection.execute(text(setup_sql))

    with pytest.raises(RuntimeError):
        upgrade_database(database)

    assert "alembic_version" not in set(inspect(database.engine).get_table_names())
