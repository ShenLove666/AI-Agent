from __future__ import annotations

import logging

from sqlalchemy import inspect, text

from app.framework.database import Database


BASELINE_COLUMNS = {
    "users_v2": {
        "id",
        "username",
        "password_hash",
        "email",
        "is_active",
        "role",
        "created_at",
        "updated_at",
    },
    "conversations": {
        "id",
        "user_id",
        "title",
        "created_at",
        "updated_at",
        "last_message_at",
    },
    "conversation_turns": {
        "id",
        "conversation_id",
        "sequence",
        "user_message_id",
        "active_assistant_message_id",
        "status",
        "rag_enabled",
        "deep_thinking",
        "knowledge_base_ids_json",
        "created_at",
        "updated_at",
    },
    "messages": {
        "id",
        "conversation_id",
        "user_id",
        "turn_id",
        "version",
        "role",
        "content",
        "citations_json",
        "vote",
        "message_status",
        "thinking_content",
        "thinking_duration_ms",
        "recommended_questions_json",
        "recommended_questions_status",
        "recommended_questions_error",
        "created_at",
    },
    "chat_request_runs": {
        "id",
        "user_id",
        "request_id",
        "request_fingerprint",
        "requested_conversation_id",
        "turn_id",
        "conversation_id",
        "user_message_id",
        "assistant_message_id",
        "status",
        "error_message",
        "created_at",
        "updated_at",
    },
    "knowledge_bases": {"id", "owner_id", "name", "description", "created_at"},
    "knowledge_documents": {
        "id",
        "knowledge_base_id",
        "uploader_id",
        "filename",
        "file_type",
        "storage_path",
        "file_size",
        "status",
        "enabled",
        "error_message",
        "created_at",
    },
    "knowledge_chunks": {
        "id",
        "knowledge_base_id",
        "document_id",
        "position",
        "content",
        "enabled",
        "created_at",
    },
    "rag_trace_runs": {
        "id",
        "user_id",
        "conversation_id",
        "turn_id",
        "query",
        "rewritten_query",
        "status",
        "elapsed_ms",
        "error_message",
        "created_at",
    },
    "rag_trace_nodes": {
        "id",
        "run_id",
        "name",
        "status",
        "elapsed_ms",
        "attributes_json",
        "created_at",
    },
}

MISSING_COLUMNS = {
    "messages": {
        "vote": "INTEGER",
        "message_status": "VARCHAR(30) DEFAULT 'NORMAL'",
        "thinking_content": "TEXT",
        "thinking_duration_ms": "INTEGER",
        "recommended_questions_json": "TEXT",
        "recommended_questions_status": "VARCHAR(20) DEFAULT 'NOT_REQUESTED'",
        "recommended_questions_error": "TEXT",
        "turn_id": "INTEGER",
        "version": "INTEGER",
    },
    "conversations": {"last_message_at": "DATETIME"},
    "chat_request_runs": {
        "request_fingerprint": "VARCHAR(64)",
        "requested_conversation_id": "VARCHAR(36)",
        "turn_id": "INTEGER",
    },
    "rag_trace_runs": {"turn_id": "INTEGER"},
    "knowledge_documents": {"enabled": "BOOLEAN NOT NULL DEFAULT 1"},
    "knowledge_chunks": {"enabled": "BOOLEAN NOT NULL DEFAULT 1"},
}


def adopt_pre_alembic_schema(database: Database) -> None:
    """Bring known pre-Alembic databases to revision 0001 shape exactly once."""
    inspector = inspect(database.engine)
    tables = set(inspector.get_table_names())
    expected_tables = set(BASELINE_COLUMNS)
    if tables != expected_tables:
        raise RuntimeError(
            "Refusing to adopt unrecognized pre-Alembic schema: "
            f"missing tables={sorted(expected_tables - tables)}, "
            f"unexpected tables={sorted(tables - expected_tables)}"
        )

    for table_name, expected_columns in BASELINE_COLUMNS.items():
        existing = {column["name"] for column in inspector.get_columns(table_name)}
        allowed_missing = set(MISSING_COLUMNS.get(table_name, {}))
        missing_required = expected_columns - existing - allowed_missing
        unexpected = existing - expected_columns
        if missing_required or unexpected:
            raise RuntimeError(
                "Refusing to adopt unrecognized pre-Alembic table "
                f"{table_name}: missing columns={sorted(missing_required)}, "
                f"unexpected columns={sorted(unexpected)}"
            )

    for table_name, wanted in MISSING_COLUMNS.items():
        existing = {column["name"] for column in inspector.get_columns(table_name)}
        for column in sorted(set(wanted) - existing):
            try:
                with database.engine.begin() as connection:
                    connection.execute(
                        text(f"ALTER TABLE {table_name} ADD COLUMN {column} {wanted[column]}")
                    )
            except Exception as exc:  # pragma: no cover - legacy database variance
                logging.getLogger("ragent.database").exception(
                    "无法为 %s 增加列 %s", table_name, column, exc_info=exc
                )
                raise
