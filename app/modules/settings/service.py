from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.framework.config import Settings
from app.framework.database import Database
from app.framework.errors import AppError
from app.modules.settings.models import RuntimeSetting, RuntimeSettingAudit
from app.modules.settings.repository import RuntimeSettingsRepository

# 需重启生效的配置项 → 环境变量名映射（启动时合并回 os.environ）
RESTART_ENV_MAP: dict[str, str] = {
    "chat_timeout_seconds": "CHAT_TIMEOUT_SECONDS",
    "chat_first_token_timeout_seconds": "CHAT_FIRST_TOKEN_TIMEOUT_SECONDS",
    "chat_idle_timeout_seconds": "CHAT_IDLE_TIMEOUT_SECONDS",
    "circuit_failure_threshold": "CIRCUIT_FAILURE_THRESHOLD",
    "circuit_recovery_seconds": "CIRCUIT_RECOVERY_SECONDS",
    "max_upload_file_size": "MAX_UPLOAD_FILE_SIZE",
    "deepseek_api_key": "DEEPSEEK_API_KEY",
    "deepseek_base_url": "DEEPSEEK_BASE_URL",
    "deepseek_model": "DEEPSEEK_MODEL",
    "vision_model": "VISION_MODEL",
}


def apply_restart_env_overrides(database: Database) -> bool:
    """启动时把 runtime_settings 中需重启生效的覆盖值合并进 os.environ。

    返回是否发生了合并（调用方据此重建容器使新配置生效）。
    """
    with database.session_factory() as db:
        rows = db.scalars(
            select(RuntimeSetting).where(RuntimeSetting.scope == "restart")
        ).all()
    merged = False
    for row in rows:
        env_key = RESTART_ENV_MAP.get(row.key)
        if not env_key:
            continue
        value = json.loads(row.value_json)
        if value is None or value == "":
            continue
        os.environ[env_key] = str(value)
        merged = True
    return merged


@dataclass(frozen=True, slots=True)
class SettingSpec:
    """白名单配置项定义。"""

    key: str
    label: str
    description: str
    scope: str  # immediate | restart
    value_type: str  # int | float | str | secret
    default: Any
    min: float | None = None
    max: float | None = None
    enum: tuple[str, ...] | None = None


def _build_whitelist(settings: Settings) -> dict[str, SettingSpec]:
    return {
        spec.key: spec
        for spec in [
            SettingSpec(
                key="retrieval_candidate_limit",
                label="检索候选数",
                description="融合前各通道候选数量",
                scope="immediate",
                value_type="int",
                default=settings.retrieval_candidate_limit,
                min=5,
                max=100,
            ),
            SettingSpec(
                key="retrieval_context_limit",
                label="上下文资料数",
                description="进入 Prompt 的上下文条数",
                scope="immediate",
                value_type="int",
                default=settings.retrieval_context_limit,
                min=1,
                max=30,
            ),
            SettingSpec(
                key="retrieval_timeout_seconds",
                label="检索超时（秒）",
                description="单通道检索超时时间",
                scope="immediate",
                value_type="float",
                default=settings.retrieval_timeout_seconds,
                min=1,
                max=30,
            ),
            SettingSpec(
                key="chat_knowledge_release_gate",
                label="聊天知识发布门禁",
                description=(
                    "开启后顾客聊天仅可检索已发布并激活知识版本内的文档"
                    "（未发布/已禁用文档不可见）；关闭则按全量已索引文档检索"
                ),
                scope="immediate",
                value_type="str",
                enum=("false", "true"),
                default="false",
            ),
            SettingSpec(
                key="prompt_history_token_budget",
                label="历史 Token 预算",
                description="进入 Prompt 的对话历史 token 上限",
                scope="immediate",
                value_type="int",
                default=settings.prompt_history_token_budget,
                min=500,
                max=8000,
            ),
            SettingSpec(
                key="prompt_context_token_budget",
                label="资料 Token 预算",
                description="检索资料在 Prompt 中的 token 上限",
                scope="immediate",
                value_type="int",
                default=settings.prompt_context_token_budget,
                min=500,
                max=10000,
            ),
            SettingSpec(
                key="chat_timeout_seconds",
                label="生成总超时（秒）",
                description="模型生成总超时，重启后生效",
                scope="restart",
                value_type="float",
                default=settings.chat_timeout_seconds,
                min=10,
                max=600,
            ),
            SettingSpec(
                key="chat_first_token_timeout_seconds",
                label="首 Token 超时（秒）",
                description="首个 Token 超时，重启后生效",
                scope="restart",
                value_type="float",
                default=settings.chat_first_token_timeout_seconds,
                min=5,
                max=120,
            ),
            SettingSpec(
                key="chat_idle_timeout_seconds",
                label="Token 间隔超时（秒）",
                description="Token 间空闲超时，重启后生效",
                scope="restart",
                value_type="float",
                default=settings.chat_idle_timeout_seconds,
                min=5,
                max=180,
            ),
            SettingSpec(
                key="circuit_failure_threshold",
                label="熔断失败阈值",
                description="连续失败次数达到阈值后断开，重启后生效",
                scope="restart",
                value_type="int",
                default=settings.circuit_failure_threshold,
                min=1,
                max=20,
            ),
            SettingSpec(
                key="circuit_recovery_seconds",
                label="熔断恢复窗口（秒）",
                description="熔断后试探恢复的等待时间，重启后生效",
                scope="restart",
                value_type="float",
                default=settings.circuit_recovery_seconds,
                min=5,
                max=600,
            ),
            SettingSpec(
                key="max_upload_file_size",
                label="上传文件上限（字节）",
                description="单文件最大字节数，重启后生效",
                scope="restart",
                value_type="int",
                default=int(
                    __import__("os").getenv("MAX_UPLOAD_FILE_SIZE", "52428800")
                ),
                min=1024 * 1024,
                max=200 * 1024 * 1024,
            ),
            SettingSpec(
                key="deepseek_api_key",
                label="DeepSeek API Key",
                description="模型服务密钥，仅显示是否已配置，重启后生效",
                scope="restart",
                value_type="secret",
                default="",
            ),
            SettingSpec(
                key="deepseek_base_url",
                label="DeepSeek Base URL",
                description="模型服务地址，重启后生效",
                scope="restart",
                value_type="str",
                default=__import__("os").getenv(
                    "DEEPSEEK_BASE_URL", "https://api.deepseek.com"
                ),
            ),
            SettingSpec(
                key="deepseek_model",
                label="DeepSeek 模型名",
                description="主对话模型，重启后生效",
                scope="restart",
                value_type="str",
                default=__import__("os").getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
            ),
            SettingSpec(
                key="vision_model",
                label="视觉模型名",
                description="识图视觉模型，重启后生效",
                scope="restart",
                value_type="str",
                default=__import__("os").getenv("VISION_MODEL", "mimo-v2.5"),
            ),
        ]
    }


class RuntimeSettingsService:
    def __init__(self, settings: Settings, repository: RuntimeSettingsRepository):
        self._settings = settings
        self._repository = repository
        self._whitelist = _build_whitelist(settings)

    @property
    def whitelist(self) -> dict[str, SettingSpec]:
        return self._whitelist

    def snapshot(self, db: Session, operator_name: str | None = None) -> dict:
        """GET 视图：白名单全量 + 当前覆盖值 + 全局版本 + 最近审计。"""
        overrides = self._repository.get_all(db)
        items = []
        for key, spec in self._whitelist.items():
            present = key in overrides
            value = overrides[key] if present else spec.default
            if spec.value_type == "secret":
                items.append(
                    {
                        "key": key,
                        "label": spec.label,
                        "description": spec.description,
                        "scope": spec.scope,
                        "valueType": spec.value_type,
                        "configured": bool(value),
                        "value": None,
                        "default": None,
                        "overridden": present,
                        "enum": list(spec.enum) if spec.enum else None,
                    }
                )
            else:
                items.append(
                    {
                        "key": key,
                        "label": spec.label,
                        "description": spec.description,
                        "scope": spec.scope,
                        "valueType": spec.value_type,
                        "configured": True,
                        "value": value,
                        "default": spec.default,
                        "overridden": present,
                        "enum": list(spec.enum) if spec.enum else None,
                    }
                )
        audits = db.scalars(
            select(RuntimeSettingAudit)
            .order_by(RuntimeSettingAudit.id.desc())
            .limit(20)
        ).all()
        return {
            "version": self._repository.get_version(db),
            "items": items,
            "audits": [
                {
                    "key": item.key,
                    "operation": item.operation,
                    "oldValue": item.old_value_json,
                    "newValue": item.new_value_json,
                    "operatorName": item.operator_name,
                    "scope": item.scope,
                    "createdAt": item.created_at.isoformat(),
                }
                for item in audits
            ],
        }

    def validate_change(self, key: str, value: Any) -> Any:
        spec = self._whitelist.get(key)
        if spec is None:
            raise AppError("SETTINGS_UNKNOWN_KEY", f"不允许修改配置项：{key}", 400)
        try:
            if spec.value_type == "int":
                value = int(value)
                if spec.min is not None and value < spec.min:
                    raise ValueError(f"最小值为 {spec.min}")
                if spec.max is not None and value > spec.max:
                    raise ValueError(f"最大值为 {spec.max}")
            elif spec.value_type == "float":
                value = float(value)
                if spec.min is not None and value < spec.min:
                    raise ValueError(f"最小值为 {spec.min}")
                if spec.max is not None and value > spec.max:
                    raise ValueError(f"最大值为 {spec.max}")
            elif spec.value_type in {"str", "secret"}:
                value = str(value).strip()
                if not value:
                    raise ValueError("不能为空")
                if len(value) > 500:
                    raise ValueError("长度不能超过 500")
            return value
        except (TypeError, ValueError) as exc:
            raise AppError(
                "SETTINGS_INVALID_VALUE",
                f"配置项 {key} 取值无效：{exc}",
                400,
            ) from exc

    def apply(
        self,
        db: Session,
        *,
        changes: dict[str, Any],
        reset_keys: list[str],
        expected_version: int,
        operator_id: int | None,
        operator_name: str | None,
    ) -> int:
        validated = {
            key: self.validate_change(key, value) for key, value in changes.items()
        }
        unknown = [key for key in reset_keys if key not in self._whitelist]
        if unknown:
            raise AppError(
                "SETTINGS_UNKNOWN_KEY", f"不允许修改配置项：{unknown[0]}", 400
            )
        new_version = expected_version
        scopes = {key: spec.scope for key, spec in self._whitelist.items()}
        if validated:
            new_version = self._repository.apply_changes(
                db,
                changes=validated,
                expected_version=expected_version,
                operator_id=operator_id,
                operator_name=operator_name,
                scopes=scopes,
            )
        if reset_keys:
            new_version = self._repository.reset_keys(
                db,
                keys=reset_keys,
                expected_version=new_version,
                operator_id=operator_id,
                operator_name=operator_name,
                scopes=scopes,
            )
        return new_version
