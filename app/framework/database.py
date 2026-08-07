from __future__ import annotations

import os
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import NullPool


class Base(DeclarativeBase):
    pass


class Database:
    def __init__(self, database_url: str | None = None):
        url = database_url or os.getenv("DB_URL", "sqlite:///./data/ragent-v4-flash.db")
        kwargs: dict = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            kwargs.update(connect_args={"check_same_thread": False}, poolclass=NullPool)
        self.engine = create_engine(url, **kwargs)
        self.session_factory = sessionmaker(
            bind=self.engine, autocommit=False, autoflush=False, expire_on_commit=False
        )

    def create_schema(self) -> None:
        """Deprecated test-only compatibility wrapper."""
        from app.framework.migrations import upgrade_database

        upgrade_database(self)

    def session(self) -> Generator[Session, None, None]:
        database_session = self.session_factory()
        try:
            yield database_session
        finally:
            database_session.close()
