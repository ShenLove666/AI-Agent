from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.api.dependencies import CurrentUser, DbSession
from app.framework.errors import AppError
from app.framework.response import ApiResponse
from app.framework.trace import current_trace_id
from app.modules.settings.service import RuntimeSettingsService
from app.modules.users.permissions import PERM_SETTINGS_WRITE
from app.modules.users.access import has_permission


router = APIRouter(tags=["runtime-settings"])


class SettingsChange(BaseModel):
    key: str = Field(min_length=1, max_length=100)
    value: Any


class SettingsPatchRequest(BaseModel):
    expectedVersion: int = Field(ge=1)
    changes: list[SettingsChange] = Field(default_factory=list, max_length=30)
    resetKeys: list[str] = Field(default_factory=list, max_length=30)


@router.get("/rag/settings", response_model=ApiResponse)
def rag_settings(db: DbSession, user: CurrentUser, request: Request) -> ApiResponse:
    service: RuntimeSettingsService = request.app.state.container.runtime_settings
    return ApiResponse(
        data=service.snapshot(db), traceId=current_trace_id()
    )


@router.patch("/rag/settings", response_model=ApiResponse)
def patch_settings(
    payload: SettingsPatchRequest,
    db: DbSession,
    user: CurrentUser,
    request: Request,
) -> ApiResponse:
    if not has_permission(db, user, PERM_SETTINGS_WRITE):
        raise AppError("FORBIDDEN", "需要 settings.write 权限", 403)
    service: RuntimeSettingsService = request.app.state.container.runtime_settings
    if not payload.changes and not payload.resetKeys:
        raise AppError("SETTINGS_EMPTY_PATCH", "没有需要修改的配置项", 400)
    new_version = service.apply(
        db,
        changes={item.key: item.value for item in payload.changes},
        reset_keys=payload.resetKeys,
        expected_version=payload.expectedVersion,
        operator_id=int(user.id),
        operator_name=user.username,
    )
    return ApiResponse(
        data={"version": new_version}, traceId=current_trace_id()
    )
