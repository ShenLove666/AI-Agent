from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from sqlalchemy import inspect
from sqlalchemy.engine import Connection

from app.framework.database import Database


ColumnDefinition = tuple[str, str, bool]
ColumnSignature = tuple[str, str, bool, str | None]
ConstraintSignature = tuple[str | None, tuple[str, ...]]
ForeignKeySignature = tuple[str | None, tuple[str, ...], str, tuple[str, ...]]
IndexSignature = tuple[str | None, tuple[str, ...], bool]


@dataclass(frozen=True)
class TableSignature:
    columns: tuple[ColumnSignature, ...]
    primary_key: ConstraintSignature
    uniques: tuple[ConstraintSignature, ...] = ()
    foreign_keys: tuple[ForeignKeySignature, ...] = ()
    indexes: tuple[IndexSignature, ...] = ()


def _table(
    columns: tuple[ColumnDefinition, ...],
    *,
    primary_key: tuple[str, ...] = ("id",),
    uniques: tuple[ConstraintSignature, ...] = (),
    foreign_keys: tuple[ForeignKeySignature, ...] = (),
    indexes: tuple[IndexSignature, ...] = (),
) -> TableSignature:
    return TableSignature(
        columns=tuple((*column, None) for column in columns),
        primary_key=(None, primary_key),
        uniques=tuple(sorted(uniques, key=repr)),
        foreign_keys=tuple(sorted(foreign_keys, key=repr)),
        indexes=tuple(sorted(indexes, key=repr)),
    )


# Frozen revision-0001 structure. Do not derive this from current Base.metadata:
# later model additions belong to later Alembic revisions, not legacy adoption.
REVISION_0001_SIGNATURE = {
    "users_v2": _table(
        (
            ("id", "INTEGER", False),
            ("username", "VARCHAR(50)", False),
            ("password_hash", "VARCHAR(255)", False),
            ("email", "VARCHAR(100)", True),
            ("is_active", "BOOLEAN", False),
            ("role", "VARCHAR(20)", False),
            ("created_at", "DATETIME", False),
            ("updated_at", "DATETIME", False),
        ),
        uniques=((None, ("email",)),),
        indexes=(("ix_users_v2_username", ("username",), True),),
    ),
    "conversations": _table(
        (
            ("id", "VARCHAR(36)", False),
            ("user_id", "INTEGER", False),
            ("title", "VARCHAR(200)", False),
            ("created_at", "DATETIME", False),
            ("updated_at", "DATETIME", False),
            ("last_message_at", "DATETIME", False),
        ),
        foreign_keys=((None, ("user_id",), "users_v2", ("id",)),),
        indexes=(("ix_conversations_user_id", ("user_id",), False),),
    ),
    "conversation_turns": _table(
        (
            ("id", "INTEGER", False),
            ("conversation_id", "VARCHAR(36)", False),
            ("sequence", "INTEGER", False),
            ("user_message_id", "INTEGER", True),
            ("active_assistant_message_id", "INTEGER", True),
            ("status", "VARCHAR(20)", False),
            ("rag_enabled", "BOOLEAN", False),
            ("deep_thinking", "BOOLEAN", False),
            ("knowledge_base_ids_json", "TEXT", False),
            ("created_at", "DATETIME", False),
            ("updated_at", "DATETIME", False),
        ),
        uniques=(
            ("uq_turn_conversation_sequence", ("conversation_id", "sequence")),
        ),
        foreign_keys=(
            (None, ("active_assistant_message_id",), "messages", ("id",)),
            (None, ("conversation_id",), "conversations", ("id",)),
            (None, ("user_message_id",), "messages", ("id",)),
        ),
        indexes=(
            ("ix_conversation_turns_conversation_id", ("conversation_id",), False),
        ),
    ),
    "messages": _table(
        (
            ("id", "INTEGER", False),
            ("conversation_id", "VARCHAR(36)", False),
            ("user_id", "INTEGER", False),
            ("turn_id", "INTEGER", True),
            ("version", "INTEGER", True),
            ("role", "VARCHAR(20)", False),
            ("content", "TEXT", False),
            ("citations_json", "TEXT", True),
            ("vote", "INTEGER", True),
            ("message_status", "VARCHAR(30)", False),
            ("thinking_content", "TEXT", True),
            ("thinking_duration_ms", "INTEGER", True),
            ("recommended_questions_json", "TEXT", True),
            ("recommended_questions_status", "VARCHAR(20)", False),
            ("recommended_questions_error", "TEXT", True),
            ("created_at", "DATETIME", False),
        ),
        foreign_keys=(
            (None, ("conversation_id",), "conversations", ("id",)),
            (None, ("turn_id",), "conversation_turns", ("id",)),
            (None, ("user_id",), "users_v2", ("id",)),
        ),
        indexes=(
            ("ix_messages_conversation_id", ("conversation_id",), False),
            ("ix_messages_turn_id", ("turn_id",), False),
            ("ix_messages_user_id", ("user_id",), False),
        ),
    ),
    "chat_request_runs": _table(
        (
            ("id", "INTEGER", False),
            ("user_id", "INTEGER", False),
            ("request_id", "VARCHAR(64)", False),
            ("request_fingerprint", "VARCHAR(64)", False),
            ("requested_conversation_id", "VARCHAR(36)", True),
            ("turn_id", "INTEGER", True),
            ("conversation_id", "VARCHAR(36)", True),
            ("user_message_id", "INTEGER", True),
            ("assistant_message_id", "INTEGER", True),
            ("status", "VARCHAR(20)", False),
            ("error_message", "TEXT", True),
            ("created_at", "DATETIME", False),
            ("updated_at", "DATETIME", False),
        ),
        uniques=(("uq_chat_request_user_id", ("user_id", "request_id")),),
        foreign_keys=(
            (None, ("assistant_message_id",), "messages", ("id",)),
            (None, ("conversation_id",), "conversations", ("id",)),
            (None, ("turn_id",), "conversation_turns", ("id",)),
            (None, ("user_id",), "users_v2", ("id",)),
            (None, ("user_message_id",), "messages", ("id",)),
        ),
        indexes=(
            ("ix_chat_request_runs_conversation_id", ("conversation_id",), False),
            ("ix_chat_request_runs_turn_id", ("turn_id",), False),
            ("ix_chat_request_runs_user_id", ("user_id",), False),
        ),
    ),
    "knowledge_bases": _table(
        (
            ("id", "INTEGER", False),
            ("owner_id", "INTEGER", False),
            ("name", "VARCHAR(100)", False),
            ("description", "TEXT", True),
            ("created_at", "DATETIME", False),
        ),
        foreign_keys=((None, ("owner_id",), "users_v2", ("id",)),),
        indexes=(("ix_knowledge_bases_owner_id", ("owner_id",), False),),
    ),
    "knowledge_documents": _table(
        (
            ("id", "INTEGER", False),
            ("knowledge_base_id", "INTEGER", False),
            ("uploader_id", "INTEGER", False),
            ("filename", "VARCHAR(255)", False),
            ("file_type", "VARCHAR(30)", False),
            ("storage_path", "VARCHAR(500)", False),
            ("file_size", "INTEGER", False),
            ("status", "VARCHAR(30)", False),
            ("enabled", "BOOLEAN", False),
            ("error_message", "TEXT", True),
            ("created_at", "DATETIME", False),
        ),
        foreign_keys=(
            (None, ("knowledge_base_id",), "knowledge_bases", ("id",)),
            (None, ("uploader_id",), "users_v2", ("id",)),
        ),
        indexes=(
            (
                "ix_knowledge_documents_knowledge_base_id",
                ("knowledge_base_id",),
                False,
            ),
            ("ix_knowledge_documents_uploader_id", ("uploader_id",), False),
        ),
    ),
    "knowledge_chunks": _table(
        (
            ("id", "INTEGER", False),
            ("knowledge_base_id", "INTEGER", False),
            ("document_id", "INTEGER", False),
            ("position", "INTEGER", False),
            ("content", "TEXT", False),
            ("enabled", "BOOLEAN", False),
            ("created_at", "DATETIME", False),
        ),
        foreign_keys=(
            (None, ("document_id",), "knowledge_documents", ("id",)),
            (None, ("knowledge_base_id",), "knowledge_bases", ("id",)),
        ),
        indexes=(
            ("ix_knowledge_chunks_document_id", ("document_id",), False),
            (
                "ix_knowledge_chunks_knowledge_base_id",
                ("knowledge_base_id",),
                False,
            ),
        ),
    ),
    "rag_trace_runs": _table(
        (
            ("id", "VARCHAR(32)", False),
            ("user_id", "INTEGER", False),
            ("conversation_id", "VARCHAR(36)", True),
            ("turn_id", "INTEGER", True),
            ("query", "TEXT", False),
            ("rewritten_query", "TEXT", True),
            ("status", "VARCHAR(20)", False),
            ("elapsed_ms", "FLOAT", True),
            ("error_message", "TEXT", True),
            ("created_at", "DATETIME", False),
        ),
        foreign_keys=((None, ("user_id",), "users_v2", ("id",)),),
        indexes=(
            ("ix_rag_trace_runs_conversation_id", ("conversation_id",), False),
            ("ix_rag_trace_runs_turn_id", ("turn_id",), False),
            ("ix_rag_trace_runs_user_id", ("user_id",), False),
        ),
    ),
    "rag_trace_nodes": _table(
        (
            ("id", "INTEGER", False),
            ("run_id", "VARCHAR(32)", False),
            ("name", "VARCHAR(100)", False),
            ("status", "VARCHAR(20)", False),
            ("elapsed_ms", "FLOAT", False),
            ("attributes_json", "TEXT", True),
            ("created_at", "DATETIME", False),
        ),
        foreign_keys=((None, ("run_id",), "rag_trace_runs", ("id",)),),
        indexes=(("ix_rag_trace_nodes_run_id", ("run_id",), False),),
    ),
}


LEGACY_REMOVED_COLUMNS = {
    "conversations": {"last_message_at"},
    "messages": {
        "turn_id",
        "version",
        "vote",
        "message_status",
        "thinking_content",
        "thinking_duration_ms",
        "recommended_questions_json",
        "recommended_questions_status",
        "recommended_questions_error",
    },
    "chat_request_runs": {
        "request_fingerprint",
        "requested_conversation_id",
        "turn_id",
    },
    "rag_trace_runs": {"turn_id"},
    "knowledge_documents": {"enabled"},
    "knowledge_chunks": {"enabled"},
}


def _legacy_signature() -> dict[str, TableSignature]:
    signature = {}
    for table_name, current in REVISION_0001_SIGNATURE.items():
        removed = LEGACY_REMOVED_COLUMNS.get(table_name, set())
        signature[table_name] = TableSignature(
            columns=tuple(
                column for column in current.columns if column[0] not in removed
            ),
            primary_key=current.primary_key,
            uniques=current.uniques,
            foreign_keys=tuple(
                constraint
                for constraint in current.foreign_keys
                if not (set(constraint[1]) & removed)
            ),
            indexes=tuple(
                index for index in current.indexes if not (set(index[1]) & removed)
            ),
        )
    return signature


SUPPORTED_LEGACY_SIGNATURE = _legacy_signature()


def schema_signature(connection: Connection) -> dict[str, TableSignature]:
    inspector = inspect(connection)
    signature = {}
    for table_name in sorted(
        table for table in inspector.get_table_names() if table != "alembic_version"
    ):
        primary_key = inspector.get_pk_constraint(table_name)
        signature[table_name] = TableSignature(
            columns=tuple(
                (
                    column["name"],
                    str(column["type"]).upper(),
                    bool(column["nullable"]),
                    column.get("default"),
                )
                for column in inspector.get_columns(table_name)
            ),
            primary_key=(
                primary_key.get("name"),
                tuple(primary_key.get("constrained_columns") or ()),
            ),
            uniques=tuple(
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
            foreign_keys=tuple(
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
            indexes=tuple(
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
        )
    return signature


def _signature_mismatch(
    actual: dict[str, TableSignature], expected: dict[str, TableSignature]
) -> str:
    details = []
    actual_tables = set(actual)
    expected_tables = set(expected)
    if missing := expected_tables - actual_tables:
        details.append(f"missing tables={sorted(missing)}")
    if unexpected := actual_tables - expected_tables:
        details.append(f"unexpected tables={sorted(unexpected)}")
    for table_name in sorted(actual_tables & expected_tables):
        if actual[table_name] == expected[table_name]:
            continue
        changed = [
            field
            for field in (
                "columns",
                "primary_key",
                "uniques",
                "foreign_keys",
                "indexes",
            )
            if getattr(actual[table_name], field) != getattr(expected[table_name], field)
        ]
        details.append(f"{table_name} differs in {changed}")
    return "; ".join(details)


def verify_revision_0001_schema(connection: Connection) -> None:
    actual = schema_signature(connection)
    if actual != REVISION_0001_SIGNATURE:
        raise RuntimeError(
            "Schema is not equivalent to revision 0001: "
            + _signature_mismatch(actual, REVISION_0001_SIGNATURE)
        )


@dataclass(frozen=True)
class RebuildStep:
    table_name: str
    create_sql: str
    copy_sql: str
    indexes: tuple[str, ...]


REBUILD_STEPS = (
    RebuildStep(
        "conversations",
        """
        CREATE TABLE _ragent_new_conversations (
            id VARCHAR(36) NOT NULL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users_v2 (id),
            title VARCHAR(200) NOT NULL,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            last_message_at DATETIME NOT NULL
        )
        """,
        """
        INSERT INTO _ragent_new_conversations (
            id, user_id, title, created_at, updated_at, last_message_at
        )
        SELECT id, user_id, title, created_at, updated_at, updated_at
        FROM conversations
        """,
        ("CREATE INDEX ix_conversations_user_id ON conversations (user_id)",),
    ),
    RebuildStep(
        "messages",
        """
        CREATE TABLE _ragent_new_messages (
            id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
            conversation_id VARCHAR(36) NOT NULL REFERENCES conversations (id),
            user_id INTEGER NOT NULL REFERENCES users_v2 (id),
            turn_id INTEGER REFERENCES conversation_turns (id),
            version INTEGER,
            role VARCHAR(20) NOT NULL,
            content TEXT NOT NULL,
            citations_json TEXT,
            vote INTEGER,
            message_status VARCHAR(30) NOT NULL,
            thinking_content TEXT,
            thinking_duration_ms INTEGER,
            recommended_questions_json TEXT,
            recommended_questions_status VARCHAR(20) NOT NULL,
            recommended_questions_error TEXT,
            created_at DATETIME NOT NULL
        )
        """,
        """
        INSERT INTO _ragent_new_messages (
            id, conversation_id, user_id, turn_id, version, role, content,
            citations_json, vote, message_status, thinking_content,
            thinking_duration_ms, recommended_questions_json,
            recommended_questions_status, recommended_questions_error, created_at
        )
        SELECT id, conversation_id, user_id, NULL, NULL, role, content,
               citations_json, NULL, 'NORMAL', NULL, NULL, NULL,
               'NOT_REQUESTED', NULL, created_at
        FROM messages
        """,
        (
            "CREATE INDEX ix_messages_conversation_id ON messages (conversation_id)",
            "CREATE INDEX ix_messages_turn_id ON messages (turn_id)",
            "CREATE INDEX ix_messages_user_id ON messages (user_id)",
        ),
    ),
    RebuildStep(
        "chat_request_runs",
        """
        CREATE TABLE _ragent_new_chat_request_runs (
            id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users_v2 (id),
            request_id VARCHAR(64) NOT NULL,
            request_fingerprint VARCHAR(64) NOT NULL,
            requested_conversation_id VARCHAR(36),
            turn_id INTEGER REFERENCES conversation_turns (id),
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
        """
        INSERT INTO _ragent_new_chat_request_runs (
            id, user_id, request_id, request_fingerprint,
            requested_conversation_id, turn_id, conversation_id,
            user_message_id, assistant_message_id, status, error_message,
            created_at, updated_at
        )
        SELECT id, user_id, request_id, request_id, conversation_id, NULL,
               conversation_id, user_message_id, assistant_message_id, status,
               error_message, created_at, updated_at
        FROM chat_request_runs
        """,
        (
            """
            CREATE INDEX ix_chat_request_runs_conversation_id
            ON chat_request_runs (conversation_id)
            """,
            "CREATE INDEX ix_chat_request_runs_turn_id ON chat_request_runs (turn_id)",
            "CREATE INDEX ix_chat_request_runs_user_id ON chat_request_runs (user_id)",
        ),
    ),
    RebuildStep(
        "rag_trace_runs",
        """
        CREATE TABLE _ragent_new_rag_trace_runs (
            id VARCHAR(32) NOT NULL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users_v2 (id),
            conversation_id VARCHAR(36),
            turn_id INTEGER,
            query TEXT NOT NULL,
            rewritten_query TEXT,
            status VARCHAR(20) NOT NULL,
            elapsed_ms FLOAT,
            error_message TEXT,
            created_at DATETIME NOT NULL
        )
        """,
        """
        INSERT INTO _ragent_new_rag_trace_runs (
            id, user_id, conversation_id, turn_id, query, rewritten_query,
            status, elapsed_ms, error_message, created_at
        )
        SELECT id, user_id, conversation_id, NULL, query, rewritten_query,
               status, elapsed_ms, error_message, created_at
        FROM rag_trace_runs
        """,
        (
            """
            CREATE INDEX ix_rag_trace_runs_conversation_id
            ON rag_trace_runs (conversation_id)
            """,
            "CREATE INDEX ix_rag_trace_runs_turn_id ON rag_trace_runs (turn_id)",
            "CREATE INDEX ix_rag_trace_runs_user_id ON rag_trace_runs (user_id)",
        ),
    ),
    RebuildStep(
        "knowledge_documents",
        """
        CREATE TABLE _ragent_new_knowledge_documents (
            id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
            knowledge_base_id INTEGER NOT NULL REFERENCES knowledge_bases (id),
            uploader_id INTEGER NOT NULL REFERENCES users_v2 (id),
            filename VARCHAR(255) NOT NULL,
            file_type VARCHAR(30) NOT NULL,
            storage_path VARCHAR(500) NOT NULL,
            file_size INTEGER NOT NULL,
            status VARCHAR(30) NOT NULL,
            enabled BOOLEAN NOT NULL,
            error_message TEXT,
            created_at DATETIME NOT NULL
        )
        """,
        """
        INSERT INTO _ragent_new_knowledge_documents (
            id, knowledge_base_id, uploader_id, filename, file_type,
            storage_path, file_size, status, enabled, error_message, created_at
        )
        SELECT id, knowledge_base_id, uploader_id, filename, file_type,
               storage_path, file_size, status, 1, error_message, created_at
        FROM knowledge_documents
        """,
        (
            """
            CREATE INDEX ix_knowledge_documents_knowledge_base_id
            ON knowledge_documents (knowledge_base_id)
            """,
            """
            CREATE INDEX ix_knowledge_documents_uploader_id
            ON knowledge_documents (uploader_id)
            """,
        ),
    ),
    RebuildStep(
        "knowledge_chunks",
        """
        CREATE TABLE _ragent_new_knowledge_chunks (
            id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
            knowledge_base_id INTEGER NOT NULL REFERENCES knowledge_bases (id),
            document_id INTEGER NOT NULL REFERENCES knowledge_documents (id),
            position INTEGER NOT NULL,
            content TEXT NOT NULL,
            enabled BOOLEAN NOT NULL,
            created_at DATETIME NOT NULL
        )
        """,
        """
        INSERT INTO _ragent_new_knowledge_chunks (
            id, knowledge_base_id, document_id, position, content, enabled, created_at
        )
        SELECT id, knowledge_base_id, document_id, position, content, 1, created_at
        FROM knowledge_chunks
        """,
        (
            """
            CREATE INDEX ix_knowledge_chunks_document_id
            ON knowledge_chunks (document_id)
            """,
            """
            CREATE INDEX ix_knowledge_chunks_knowledge_base_id
            ON knowledge_chunks (knowledge_base_id)
            """,
        ),
    ),
)

REBUILD_TEMPORARY_TABLES = tuple(
    f"_ragent_new_{step.table_name}" for step in REBUILD_STEPS
)
REBUILD_CONNECTION_FLAG = "ragent_legacy_rebuild_started"


def _rebuild_supported_legacy_schema(connection: Connection) -> None:
    connection.info[REBUILD_CONNECTION_FLAG] = True
    for step in REBUILD_STEPS:
        temporary_table = f"_ragent_new_{step.table_name}"
        connection.exec_driver_sql(step.create_sql)
        connection.exec_driver_sql(step.copy_sql)
        connection.exec_driver_sql(f"DROP TABLE {step.table_name}")
        connection.exec_driver_sql(
            f"ALTER TABLE {temporary_table} RENAME TO {step.table_name}"
        )
        for statement in step.indexes:
            connection.exec_driver_sql(statement)

    violations = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise RuntimeError(f"Legacy adoption produced foreign-key violations: {violations}")
    connection.info.pop(REBUILD_CONNECTION_FLAG, None)


def _remove_rebuild_artifacts(connection: Connection) -> None:
    for table_name in REBUILD_TEMPORARY_TABLES:
        connection.exec_driver_sql(f"DROP TABLE IF EXISTS {table_name}")


def _adopt_on_connection(connection: Connection) -> None:
    if connection.dialect.name != "sqlite":
        raise RuntimeError(
            "Pre-Alembic adoption is supported only for validated SQLite schemas"
        )

    actual = schema_signature(connection)
    if actual == REVISION_0001_SIGNATURE:
        return
    if actual != SUPPORTED_LEGACY_SIGNATURE:
        raise RuntimeError(
            "Refusing to adopt unrecognized pre-Alembic schema: "
            + _signature_mismatch(actual, SUPPORTED_LEGACY_SIGNATURE)
        )

    _rebuild_supported_legacy_schema(connection)
    verify_revision_0001_schema(connection)


@contextmanager
def migration_transaction(database: Database) -> Iterator[Connection]:
    with database.engine.connect() as connection:
        restore_foreign_keys = False
        if connection.dialect.name == "sqlite":
            restore_foreign_keys = bool(
                connection.exec_driver_sql("PRAGMA foreign_keys").scalar()
            )
            connection.rollback()
            if restore_foreign_keys:
                connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
                connection.commit()
        try:
            try:
                with connection.begin():
                    yield connection
            except Exception:
                if connection.info.pop(REBUILD_CONNECTION_FLAG, False):
                    with connection.begin():
                        _remove_rebuild_artifacts(connection)
                raise
        finally:
            if restore_foreign_keys:
                if connection.in_transaction():
                    connection.rollback()
                connection.exec_driver_sql("PRAGMA foreign_keys=ON")
                connection.commit()


def adopt_pre_alembic_schema(
    database: Database, connection: Connection | None = None
) -> None:
    """Bring known pre-Alembic databases to revision 0001 shape exactly once."""
    if connection is not None:
        _adopt_on_connection(connection)
        return
    with migration_transaction(database) as owned_connection:
        _adopt_on_connection(owned_connection)
