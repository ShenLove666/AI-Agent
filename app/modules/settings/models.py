from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.framework.database import Base


class RuntimeSetting(Base):
    """运行时配置项。value_json 保存 JSON 值；scope 区分立即生效/需重启生效。"""

    __tablename__ = "runtime_settings"
    __table_args__ = (UniqueConstraint("key", name="uq_runtime_settings_key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(100))
    value_json: Mapped[str] = mapped_column(Text, default="null")
    scope: Mapped[str] = mapped_column(String(20), default="immediate")
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users_v2.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class RuntimeSettingAudit(Base):
    """配置修改审计：记录操作者、时间、旧值、新值。"""

    __tablename__ = "runtime_settings_audit"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(100), index=True)
    operation: Mapped[str] = mapped_column(String(20), default="update")
    old_value_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    operator_id: Mapped[int | None] = mapped_column(ForeignKey("users_v2.id"), nullable=True)
    operator_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    scope: Mapped[str] = mapped_column(String(20), default="immediate")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class RuntimeConfigMeta(Base):
    """全局配置版本号（单行），用于并发冲突检测 CAS。"""

    __tablename__ = "runtime_config_meta"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
