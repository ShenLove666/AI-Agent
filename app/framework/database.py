from __future__ import annotations

import logging
import os
from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import NullPool


class Base(DeclarativeBase):
    pass


class Database:
    def __init__(self, database_url: str | None = None):
        url = database_url or os.getenv("DB_URL", "sqlite:///./data/ragent.db")
        kwargs: dict = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            kwargs.update(connect_args={"check_same_thread": False}, poolclass=NullPool)
        self.engine = create_engine(url, **kwargs)
        self.session_factory = sessionmaker(
            bind=self.engine, autocommit=False, autoflush=False, expire_on_commit=False
        )

    def create_schema(self) -> None:
        Base.metadata.create_all(self.engine)
        inspector = inspect(self.engine)
        missing_columns = {
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
        for table_name, wanted in missing_columns.items():
            if table_name not in inspector.get_table_names():
                continue
            existing = {column["name"] for column in inspector.get_columns(table_name)}
            for column in sorted(set(wanted) - existing):
                try:
                    with self.engine.begin() as connection:
                        connection.execute(
                            text(
                                f"ALTER TABLE {table_name} ADD COLUMN {column} {wanted[column]}"
                            )
                        )
                except Exception as exc:  # pragma: no cover - legacy database variance
                    logging.getLogger("ragent.database").exception(
                        "无法为 %s 增加列 %s", table_name, column, exc_info=exc
                    )
                    raise

    def session(self) -> Generator[Session, None, None]:
        database_session = self.session_factory()
        try:
            yield database_session
        finally:
            database_session.close()
