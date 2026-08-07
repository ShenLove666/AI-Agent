from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from app.framework.database import Database
from app.framework.legacy_schema import adopt_pre_alembic_schema


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def build_alembic_config(url: str) -> Config:
    config = Config(str(REPOSITORY_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    config.attributes["programmatic_database_url"] = True
    return config


def upgrade_database(database: Database) -> None:
    config = build_alembic_config(
        database.engine.url.render_as_string(hide_password=False)
    )
    tables = set(inspect(database.engine).get_table_names())
    if "alembic_version" not in tables and tables:
        adopt_pre_alembic_schema(database)
        command.stamp(config, "0001_current_schema")
    command.upgrade(config, "head")
