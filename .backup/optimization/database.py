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
            kwargs.update(
                connect_args={"check_same_thread": False},
                poolclass=NullPool,
            )
        self.engine = create_engine(url, **kwargs)
        self.session_factory = sessionmaker(
            bind=self.engine, autocommit=False, autoflush=False, expire_on_commit=False
        )

    def create_schema(self) -> None:
        Base.metadata.create_all(self.engine)
        # 轻量列迁移 (SQLite/MySQL 通用): 为已存在的表补充新增列
        # 说明: create_all 只建新表, 已有表的新增列需 ALTER TABLE
        inspector = inspect(self.engine)
        missing_columns = {
            "messages": {"vote", "message_status", "thinking_content"},
            "knowledge_documents": {"enabled"},
        }
        for table_name, wanted in missing_columns.items():
            if table_name not in inspector.get_table_names():
                continue
            existing = {col["name"] for col in inspector.get_columns(table_name)}
            for column in sorted(wanted - existing):
                try:
                    with self.engine.begin() as conn:
                        conn.execute(
                            text(
                                f"ALTER TABLE {table_name} ADD COLUMN {column} "
                                f"{'INTEGER' if column == 'vote' else 'VARCHAR(30)'}"
                            )
                        )
                    logging.getLogger("ragent.database").info(
                        "已为 %s 表补充列 %s", table_name, column
                    )
                except Exception as exc:  # noqa: BLE001
                    logging.getLogger("ragent.database").warning(
                        "为 %s 表补充列 %s 失败: %s", table_name, column, exc
                    )

    def session(self) -> Generator[Session, None, None]:
        db = self.session_factory()
        try:
            yield db
        finally:
            db.close()
