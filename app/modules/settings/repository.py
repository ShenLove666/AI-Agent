from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.framework.errors import AppError
from app.modules.settings.models import RuntimeConfigMeta, RuntimeSetting, RuntimeSettingAudit


class RuntimeSettingsRepository:
    """运行时配置的持久化与版本化并发控制。"""

    def get_all(self, db: Session) -> dict[str, Any]:
        rows = db.scalars(select(RuntimeSetting)).all()
        return {
            row.key: json.loads(row.value_json)
            for row in rows
            if row.value_json not in (None, "", "null")
        }

    def get(self, db: Session, key: str) -> RuntimeSetting | None:
        return db.scalar(select(RuntimeSetting).where(RuntimeSetting.key == key))

    def get_version(self, db: Session) -> int:
        meta = db.get(RuntimeConfigMeta, 1)
        return meta.version if meta else 1

    def apply_changes(
        self,
        db: Session,
        *,
        changes: dict[str, Any],
        expected_version: int,
        operator_id: int | None,
        operator_name: str | None,
        scopes: dict[str, str],
    ) -> int:
        """按 expectedVersion 乐观锁写入变更，返回新版本号。版本冲突抛 409。"""
        now = datetime.utcnow()
        new_version = self._bump_version(db, expected_version)
        for key, value in changes.items():
            existing = self.get(db, key)
            old_value = json.loads(existing.value_json) if existing else None
            if existing is None:
                db.add(
                    RuntimeSetting(
                        key=key,
                        value_json=json.dumps(value, ensure_ascii=False),
                        scope=scopes.get(key, "immediate"),
                        updated_by=operator_id,
                        updated_at=now,
                    )
                )
            else:
                existing.value_json = json.dumps(value, ensure_ascii=False)
                existing.updated_by = operator_id
                existing.updated_at = now
            db.add(
                RuntimeSettingAudit(
                    key=key,
                    operation="update",
                    old_value_json=json.dumps(old_value, ensure_ascii=False)
                    if old_value is not None
                    else None,
                    new_value_json=json.dumps(value, ensure_ascii=False),
                    operator_id=operator_id,
                    operator_name=operator_name,
                    scope=scopes.get(key, "immediate"),
                    created_at=now,
                )
            )
        db.commit()
        return new_version

    def reset_keys(
        self,
        db: Session,
        *,
        keys: list[str],
        expected_version: int,
        operator_id: int | None,
        operator_name: str | None,
        scopes: dict[str, str],
    ) -> int:
        """恢复默认：删除覆盖记录（应用默认值来自白名单 default）。"""
        now = datetime.utcnow()
        new_version = self._bump_version(db, expected_version)
        for key in keys:
            existing = self.get(db, key)
            old_value = json.loads(existing.value_json) if existing else None
            if existing is not None:
                db.delete(existing)
            db.add(
                RuntimeSettingAudit(
                    key=key,
                    operation="reset",
                    old_value_json=json.dumps(old_value, ensure_ascii=False)
                    if old_value is not None
                    else None,
                    new_value_json=None,
                    operator_id=operator_id,
                    operator_name=operator_name,
                    scope=scopes.get(key, "immediate"),
                    created_at=now,
                )
            )
        db.commit()
        return new_version

    def _bump_version(self, db: Session, expected_version: int) -> int:
        meta = db.get(RuntimeConfigMeta, 1)
        if meta is None:
            meta = RuntimeConfigMeta(id=1, version=1)
            db.add(meta)
            db.flush()
        if meta.version != expected_version:
            raise AppError(
                "SETTINGS_VERSION_CONFLICT",
                "配置已被其他操作修改，请刷新后重试",
                409,
            )
        meta.version += 1
        db.flush()
        return meta.version
