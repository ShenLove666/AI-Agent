from __future__ import annotations

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import event, inspect, text

from app.framework.database import Base, Database
from app.framework.legacy_schema import adopt_pre_alembic_schema
from app.framework.migrations import build_alembic_config, upgrade_database

from app.modules.conversations import models as conversation_models  # noqa: F401,E402
from app.modules.commerce import models as commerce_models  # noqa: F401,E402
from app.modules.evaluation import models as evaluation_models  # noqa: F401,E402
from app.modules.knowledge import models as knowledge_models  # noqa: F401,E402
from app.modules.rag import trace_models as rag_trace_models  # noqa: F401,E402
from app.modules.operations import models as operation_models  # noqa: F401,E402
from app.modules.optimization import models as optimization_models  # noqa: F401,E402
from app.modules.users import models as user_models  # noqa: F401,E402


ALEMBIC_HEAD = ScriptDirectory.from_config(build_alembic_config("sqlite://")).get_current_head()


LEGACY_SCHEMA_SQL = (
    """
    CREATE TABLE users_v2 (
        id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
        username VARCHAR(50) NOT NULL,
        password_hash VARCHAR(255) NOT NULL,
        email VARCHAR(100),
        is_active BOOLEAN NOT NULL,
        role VARCHAR(20) NOT NULL,
        created_at DATETIME NOT NULL,
        updated_at DATETIME NOT NULL,
        UNIQUE (email)
    )
    """,
    "CREATE UNIQUE INDEX ix_users_v2_username ON users_v2 (username)",
    """
    CREATE TABLE conversations (
        id VARCHAR(36) NOT NULL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users_v2 (id),
        title VARCHAR(200) NOT NULL,
        created_at DATETIME NOT NULL,
        updated_at DATETIME NOT NULL
    )
    """,
    "CREATE INDEX ix_conversations_user_id ON conversations (user_id)",
    """
    CREATE TABLE conversation_turns (
        id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
        conversation_id VARCHAR(36) NOT NULL REFERENCES conversations (id),
        sequence INTEGER NOT NULL,
        user_message_id INTEGER REFERENCES messages (id),
        active_assistant_message_id INTEGER REFERENCES messages (id),
        status VARCHAR(20) NOT NULL,
        rag_enabled BOOLEAN NOT NULL,
        deep_thinking BOOLEAN NOT NULL,
        knowledge_base_ids_json TEXT NOT NULL,
        created_at DATETIME NOT NULL,
        updated_at DATETIME NOT NULL,
        CONSTRAINT uq_turn_conversation_sequence UNIQUE (conversation_id, sequence)
    )
    """,
    """
    CREATE INDEX ix_conversation_turns_conversation_id
    ON conversation_turns (conversation_id)
    """,
    """
    CREATE TABLE messages (
        id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
        conversation_id VARCHAR(36) NOT NULL REFERENCES conversations (id),
        user_id INTEGER NOT NULL REFERENCES users_v2 (id),
        role VARCHAR(20) NOT NULL,
        content TEXT NOT NULL,
        citations_json TEXT,
        created_at DATETIME NOT NULL
    )
    """,
    "CREATE INDEX ix_messages_conversation_id ON messages (conversation_id)",
    "CREATE INDEX ix_messages_user_id ON messages (user_id)",
    """
    CREATE TABLE chat_request_runs (
        id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users_v2 (id),
        request_id VARCHAR(64) NOT NULL,
        conversation_id VARCHAR(36) REFERENCES conversations (id),
        user_message_id INTEGER REFERENCES messages (id),
        assistant_message_id INTEGER REFERENCES messages (id),
        status VARCHAR(20) NOT NULL,
        error_message TEXT,
        created_at DATETIME NOT NULL,
        updated_at DATETIME NOT NULL,
        CONSTRAINT uq_chat_request_user_id UNIQUE (user_id, request_id)
    )
    """,
    "CREATE INDEX ix_chat_request_runs_user_id ON chat_request_runs (user_id)",
    """
    CREATE INDEX ix_chat_request_runs_conversation_id
    ON chat_request_runs (conversation_id)
    """,
    """
    CREATE TABLE knowledge_bases (
        id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
        owner_id INTEGER NOT NULL REFERENCES users_v2 (id),
        name VARCHAR(100) NOT NULL,
        description TEXT,
        created_at DATETIME NOT NULL
    )
    """,
    "CREATE INDEX ix_knowledge_bases_owner_id ON knowledge_bases (owner_id)",
    """
    CREATE TABLE knowledge_documents (
        id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
        knowledge_base_id INTEGER NOT NULL REFERENCES knowledge_bases (id),
        uploader_id INTEGER NOT NULL REFERENCES users_v2 (id),
        filename VARCHAR(255) NOT NULL,
        file_type VARCHAR(30) NOT NULL,
        storage_path VARCHAR(500) NOT NULL,
        file_size INTEGER NOT NULL,
        status VARCHAR(30) NOT NULL,
        error_message TEXT,
        created_at DATETIME NOT NULL
    )
    """,
    """
    CREATE INDEX ix_knowledge_documents_knowledge_base_id
    ON knowledge_documents (knowledge_base_id)
    """,
    """
    CREATE INDEX ix_knowledge_documents_uploader_id
    ON knowledge_documents (uploader_id)
    """,
    """
    CREATE TABLE knowledge_chunks (
        id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
        knowledge_base_id INTEGER NOT NULL REFERENCES knowledge_bases (id),
        document_id INTEGER NOT NULL REFERENCES knowledge_documents (id),
        position INTEGER NOT NULL,
        content TEXT NOT NULL,
        created_at DATETIME NOT NULL
    )
    """,
    "CREATE INDEX ix_knowledge_chunks_document_id ON knowledge_chunks (document_id)",
    """
    CREATE INDEX ix_knowledge_chunks_knowledge_base_id
    ON knowledge_chunks (knowledge_base_id)
    """,
    """
    CREATE TABLE rag_trace_runs (
        id VARCHAR(32) NOT NULL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users_v2 (id),
        conversation_id VARCHAR(36),
        query TEXT NOT NULL,
        rewritten_query TEXT,
        status VARCHAR(20) NOT NULL,
        elapsed_ms FLOAT,
        error_message TEXT,
        created_at DATETIME NOT NULL
    )
    """,
    "CREATE INDEX ix_rag_trace_runs_user_id ON rag_trace_runs (user_id)",
    """
    CREATE INDEX ix_rag_trace_runs_conversation_id
    ON rag_trace_runs (conversation_id)
    """,
    """
    CREATE TABLE rag_trace_nodes (
        id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
        run_id VARCHAR(32) NOT NULL REFERENCES rag_trace_runs (id),
        name VARCHAR(100) NOT NULL,
        status VARCHAR(20) NOT NULL,
        elapsed_ms FLOAT NOT NULL,
        attributes_json TEXT,
        created_at DATETIME NOT NULL
    )
    """,
    "CREATE INDEX ix_rag_trace_nodes_run_id ON rag_trace_nodes (run_id)",
)


def _create_legacy_schema(database: Database) -> None:
    with database.engine.begin() as connection:
        for statement in LEGACY_SCHEMA_SQL:
            connection.exec_driver_sql(statement)
        connection.execute(
            text(
                """
                INSERT INTO users_v2 (
                    id, username, password_hash, email, is_active, role,
                    created_at, updated_at
                ) VALUES (
                    1, 'legacy-user', 'hash', NULL, 1, 'user',
                    '2026-08-07 00:00:00', '2026-08-07 00:01:00'
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO conversations (
                    id, user_id, title, created_at, updated_at
                ) VALUES (
                    'conversation-1', 1, 'legacy',
                    '2026-08-07 00:00:00', '2026-08-07 00:02:00'
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO conversation_turns (
                    id, conversation_id, sequence, user_message_id,
                    active_assistant_message_id, status, rag_enabled,
                    deep_thinking, knowledge_base_ids_json, created_at, updated_at
                ) VALUES (
                    1, 'conversation-1', 1, NULL, NULL, 'completed', 1,
                    0, '[]', '2026-08-07 00:03:00', '2026-08-07 00:04:00'
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO messages (
                    id, conversation_id, user_id, role, content,
                    citations_json, created_at
                ) VALUES (
                    1, 'conversation-1', 1, 'user', 'legacy message',
                    NULL, '2026-08-07 00:05:00'
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO chat_request_runs (
                    id, user_id, request_id, conversation_id, user_message_id,
                    assistant_message_id, status, error_message, created_at, updated_at
                ) VALUES (
                    1, 1, 'request-1', 'conversation-1', 1, NULL,
                    'completed', NULL, '2026-08-07 00:06:00', '2026-08-07 00:07:00'
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO knowledge_bases (id, owner_id, name, description, created_at)
                VALUES (1, 1, 'legacy kb', NULL, '2026-08-07 00:08:00')
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO knowledge_documents (
                    id, knowledge_base_id, uploader_id, filename, file_type,
                    storage_path, file_size, status, error_message, created_at
                ) VALUES (
                    1, 1, 1, 'legacy.txt', 'txt', 'legacy.txt', 10,
                    'ready', NULL, '2026-08-07 00:09:00'
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO knowledge_chunks (
                    id, knowledge_base_id, document_id, position, content, created_at
                ) VALUES (1, 1, 1, 0, 'legacy chunk', '2026-08-07 00:10:00')
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO rag_trace_runs (
                    id, user_id, conversation_id, query, rewritten_query,
                    status, elapsed_ms, error_message, created_at
                ) VALUES (
                    'trace-1', 1, 'conversation-1', 'legacy query', NULL,
                    'completed', 1.0, NULL, '2026-08-07 00:11:00'
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO rag_trace_nodes (
                    id, run_id, name, status, elapsed_ms, attributes_json, created_at
                ) VALUES (
                    1, 'trace-1', 'retrieve', 'completed', 1.0, NULL,
                    '2026-08-07 00:12:00'
                )
                """
            )
        )


def _schema_signature(database: Database) -> dict:
    inspector = inspect(database.engine)
    signature = {}
    for table_name in sorted(
        table for table in inspector.get_table_names() if table != "alembic_version"
    ):
        primary_key = inspector.get_pk_constraint(table_name)
        signature[table_name] = {
            "columns": tuple(
                (
                    column["name"],
                    str(column["type"]).upper(),
                    bool(column["nullable"]),
                    column.get("default"),
                    bool(column.get("primary_key")),
                )
                for column in inspector.get_columns(table_name)
            ),
            "primary_key": (
                primary_key.get("name"),
                tuple(primary_key.get("constrained_columns") or ()),
            ),
            "uniques": tuple(
                sorted(
                    [
                        (
                            constraint.get("name"),
                            tuple(constraint.get("column_names") or ()),
                        )
                        for constraint in inspector.get_unique_constraints(table_name)
                    ],
                    key=repr,
                )
            ),
            "foreign_keys": tuple(
                sorted(
                    [
                        (
                            constraint.get("name"),
                            tuple(constraint.get("constrained_columns") or ()),
                            constraint.get("referred_table"),
                            tuple(constraint.get("referred_columns") or ()),
                        )
                        for constraint in inspector.get_foreign_keys(table_name)
                    ],
                    key=repr,
                )
            ),
            "indexes": tuple(
                sorted(
                    [
                        (
                            index.get("name"),
                            tuple(index.get("column_names") or ()),
                            bool(index.get("unique")),
                        )
                        for index in inspector.get_indexes(table_name)
                    ],
                    key=repr,
                )
            ),
        }
    return signature


def _current_schema_signature(tmp_path) -> dict:
    reference = Database(f"sqlite:///{tmp_path / 'reference.db'}")
    Base.metadata.create_all(reference.engine)
    return _schema_signature(reference)


def _revision_schema_signature(tmp_path, revision: str) -> dict:
    reference = Database(f"sqlite:///{tmp_path / f'{revision}.db'}")
    config = build_alembic_config(
        reference.engine.url.render_as_string(hide_password=False)
    )
    command.upgrade(config, revision)
    return _schema_signature(reference)


def test_upgrade_database_builds_empty_sqlite_schema(tmp_path):
    database = Database(f"sqlite:///{tmp_path / 'empty.db'}")

    upgrade_database(database)

    tables = set(inspect(database.engine).get_table_names())
    assert "alembic_version" in tables
    assert {"users_v2", "conversations", "messages", "knowledge_documents"} <= tables


def test_upgrade_database_adopts_current_pre_alembic_schema(tmp_path):
    database = Database(f"sqlite:///{tmp_path / 'legacy.db'}")
    config = build_alembic_config(
        database.engine.url.render_as_string(hide_password=False)
    )
    command.upgrade(config, "0001_current_schema")
    with database.engine.begin() as connection:
        connection.execute(text("DROP TABLE alembic_version"))
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
            == ALEMBIC_HEAD
        )
        assert connection.scalar(text("SELECT username FROM users_v2")) == "legacy-user"
        assert connection.scalar(text("SELECT is_demo FROM users_v2")) == 0


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


def test_rejected_unknown_schema_never_deletes_similarly_named_user_table(tmp_path):
    database = Database(f"sqlite:///{tmp_path / 'reserved-name.db'}")
    with database.engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE _ragent_new_messages (id INTEGER PRIMARY KEY, value TEXT)"
        )
        connection.execute(
            text("INSERT INTO _ragent_new_messages (id, value) VALUES (1, 'keep-me')")
        )

    with pytest.raises(RuntimeError):
        upgrade_database(database)

    with database.engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT value FROM _ragent_new_messages WHERE id=1"))
            == "keep-me"
        )


def test_upgrade_database_rebuilds_real_legacy_schema_to_exact_current_shape(tmp_path):
    database = Database(f"sqlite:///{tmp_path / 'historical.db'}")
    _create_legacy_schema(database)
    expected_signature = _current_schema_signature(tmp_path)

    upgrade_database(database)

    assert _schema_signature(database) == expected_signature
    with database.engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT version_num FROM alembic_version"))
            == ALEMBIC_HEAD
        )
        assert connection.scalar(text("SELECT username FROM users_v2")) == "legacy-user"
        assert (
            connection.scalar(text("SELECT last_message_at FROM conversations"))
            == "2026-08-07 00:02:00"
        )
        assert (
            connection.scalar(text("SELECT request_fingerprint FROM chat_request_runs"))
            == "request-1"
        )
        assert connection.scalar(text("SELECT enabled FROM knowledge_documents")) == 1
        assert connection.scalar(text("SELECT enabled FROM knowledge_chunks")) == 1
        assert connection.scalar(text("SELECT is_demo FROM users_v2")) == 0
        assert (
            connection.scalar(text("SELECT content_origin FROM knowledge_documents"))
            == "user_upload"
        )


def test_upgrade_database_rejects_legacy_schema_with_missing_index(tmp_path):
    database = Database(f"sqlite:///{tmp_path / 'wrong-constraint.db'}")
    _create_legacy_schema(database)
    with database.engine.begin() as connection:
        connection.exec_driver_sql("DROP INDEX ix_messages_user_id")

    with pytest.raises(RuntimeError):
        upgrade_database(database)

    tables = set(inspect(database.engine).get_table_names())
    assert "alembic_version" not in tables
    with database.engine.connect() as connection:
        assert connection.scalar(text("SELECT content FROM messages")) == "legacy message"


def test_completed_adoption_without_stamp_is_safe_to_retry(tmp_path):
    database = Database(f"sqlite:///{tmp_path / 'retry.db'}")
    _create_legacy_schema(database)
    revision_signature = _revision_schema_signature(tmp_path, "0001_current_schema")
    expected_signature = _current_schema_signature(tmp_path)

    adopt_pre_alembic_schema(database)

    assert "alembic_version" not in set(inspect(database.engine).get_table_names())
    assert _schema_signature(database) == revision_signature

    upgrade_database(database)

    with database.engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT version_num FROM alembic_version"))
            == ALEMBIC_HEAD
        )
        assert connection.scalar(text("SELECT content FROM messages")) == "legacy message"


def test_failed_legacy_rebuild_rolls_back_without_stamp_and_can_retry(tmp_path):
    database = Database(f"sqlite:///{tmp_path / 'failed-rebuild.db'}")
    _create_legacy_schema(database)
    legacy_signature = _schema_signature(database)
    expected_signature = _current_schema_signature(tmp_path)

    def fail_during_messages_swap(
        _connection, _cursor, statement, _parameters, _context, _executemany
    ):
        if statement.strip().upper() == "DROP TABLE MESSAGES":
            raise RuntimeError("injected rebuild failure")

    event.listen(database.engine, "before_cursor_execute", fail_during_messages_swap)
    try:
        with pytest.raises(RuntimeError, match="injected rebuild failure"):
            upgrade_database(database)
    finally:
        event.remove(
            database.engine, "before_cursor_execute", fail_during_messages_swap
        )

    assert "alembic_version" not in set(inspect(database.engine).get_table_names())
    assert _schema_signature(database) == legacy_signature

    upgrade_database(database)

    assert _schema_signature(database) == expected_signature
    with database.engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT version_num FROM alembic_version"))
            == ALEMBIC_HEAD
        )


def test_destructive_legacy_rebuild_ddl_is_inside_real_sqlite_transaction(tmp_path):
    database = Database(f"sqlite:///{tmp_path / 'atomic-rebuild.db'}")
    _create_legacy_schema(database)
    legacy_signature = _schema_signature(database)
    expected_signature = _current_schema_signature(tmp_path)
    transaction_states = []
    destructive_drops = []

    def fail_after_first_production_drop(
        connection, _cursor, statement, _parameters, _context, _executemany
    ):
        normalized = " ".join(statement.split()).upper()
        if normalized.startswith("CREATE TABLE _RAGENT_NEW_CONVERSATIONS"):
            transaction_states.append(
                connection.connection.driver_connection.in_transaction
            )
        if normalized == "DROP TABLE CONVERSATIONS":
            destructive_drops.append(normalized)
            raise RuntimeError("injected failure after production table drop")

    event.listen(
        database.engine, "after_cursor_execute", fail_after_first_production_drop
    )
    try:
        with pytest.raises(
            RuntimeError, match="injected failure after production table drop"
        ):
            upgrade_database(database)
    finally:
        event.remove(
            database.engine,
            "after_cursor_execute",
            fail_after_first_production_drop,
        )

    assert transaction_states == [True]
    assert destructive_drops == ["DROP TABLE CONVERSATIONS"]
    assert "alembic_version" not in set(inspect(database.engine).get_table_names())
    assert _schema_signature(database) == legacy_signature
    with database.engine.connect() as connection:
        assert connection.scalar(text("SELECT content FROM messages")) == "legacy message"

    upgrade_database(database)

    assert _schema_signature(database) == expected_signature
    with database.engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT version_num FROM alembic_version"))
            == ALEMBIC_HEAD
        )


def test_programmatic_database_url_wins_over_polluted_environment(
    tmp_path, monkeypatch
):
    explicit_path = tmp_path / "explicit.db"
    polluted_path = tmp_path / "deleted" / "polluted.db"
    monkeypatch.setenv("DB_URL", f"sqlite:///{polluted_path}")
    database = Database(f"sqlite:///{explicit_path}")

    upgrade_database(database)

    assert explicit_path.is_file()
    assert not polluted_path.exists()
    with database.engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT version_num FROM alembic_version"))
            == ALEMBIC_HEAD
        )


def test_upgrade_database_resolves_alembic_config_outside_repository_cwd(
    tmp_path, monkeypatch
):
    database = Database(f"sqlite:///{tmp_path / 'outside-cwd.db'}")
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.chdir(outside)

    upgrade_database(database)

    with database.engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT version_num FROM alembic_version"))
            == ALEMBIC_HEAD
        )


def test_evaluation_revision_creates_and_drops_dataset_tables(tmp_path):
    database = Database(f"sqlite:///{tmp_path / 'evaluation-revision.db'}")
    config = build_alembic_config(
        database.engine.url.render_as_string(hide_password=False)
    )

    command.upgrade(config, "0003_evaluation_datasets")

    inspector = inspect(database.engine)
    assert {"evaluation_datasets", "evaluation_cases"} <= set(
        inspector.get_table_names()
    )
    assert ("owner_id", "name") in {
        tuple(constraint.get("column_names") or ())
        for constraint in inspector.get_unique_constraints("evaluation_datasets")
    }
    assert ("dataset_id", "case_key") in {
        tuple(constraint.get("column_names") or ())
        for constraint in inspector.get_unique_constraints("evaluation_cases")
    }

    command.downgrade(config, "0002_demo_source_metadata")

    assert {"evaluation_datasets", "evaluation_cases"}.isdisjoint(
        inspect(database.engine).get_table_names()
    )


def test_real_sqlite_upgrade_can_downgrade_to_base(tmp_path):
    database = Database(f"sqlite:///{tmp_path / 'round-trip.db'}")
    upgrade_database(database)
    config = build_alembic_config(
        database.engine.url.render_as_string(hide_password=False)
    )

    command.downgrade(config, "base")

    assert set(inspect(database.engine).get_table_names()) == {"alembic_version"}
    with database.engine.connect() as connection:
        assert connection.scalar(text("SELECT COUNT(*) FROM alembic_version")) == 0
