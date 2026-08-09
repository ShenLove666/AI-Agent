from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.dependencies import CurrentUser, DbSession
from app.framework.errors import AppError
from app.framework.response import ApiResponse
from app.framework.trace import current_trace_id
from app.modules.commerce.service import RetailDataError, RetailService
from app.modules.users.access import (
    ensure_owner,
    has_permission,
)
from app.modules.users.permissions import (
    PERM_CAMPAIGN_CONFIRM,
    PERM_CAMPAIGN_CREATE,
    PERM_CAMPAIGN_PUBLISH,
    PERM_RETAIL_VIEW,
    PERM_TASK_READ,
    PERM_TASK_UPDATE,
)


router = APIRouter(prefix="/retail", tags=["instant-retail"])
data_source_router = APIRouter(prefix="/data-sources", tags=["data-provenance"])
service = RetailService()


def _owner(db, user) -> int:
    return ensure_owner(db, user)


def _safe(call):
    try:
        return call()
    except (RetailDataError, OSError, ValueError) as exc:
        raise AppError("RETAIL_OPERATION_FAILED", str(exc), 400) from exc


class ImportRequest(BaseModel):
    source_dir: str = Field(alias="sourceDir")
    seed: int = 20260807


class CampaignRequest(BaseModel):
    rule_id: int = Field(alias="ruleId")


class CampaignTransitionRequest(BaseModel):
    action: str
    expectedVersion: int = Field(alias="expectedVersion", ge=1)
    reason: str | None = None


class TaskTransitionRequest(BaseModel):
    status: str
    changeVersion: str | None = Field(default=None, alias="changeVersion")


class TaskAssignRequest(BaseModel):
    assignee_id: int | None = Field(default=None, alias="assigneeId")


@router.get("/overview")
def retail_overview(db: DbSession, user: CurrentUser) -> ApiResponse:
    if not has_permission(db, user, PERM_RETAIL_VIEW):
        raise AppError("FORBIDDEN", "需要 retail.view 权限", 403)
    return ApiResponse(
        data=service.overview(db, _owner(db, user)), traceId=current_trace_id()
    )


@router.get("/data-sources")
def retail_data_sources(db: DbSession, user: CurrentUser) -> ApiResponse:
    if not has_permission(db, user, PERM_RETAIL_VIEW):
        raise AppError("FORBIDDEN", "需要 retail.view 权限", 403)
    return ApiResponse(
        data=service.data_sources(db, _owner(db, user)), traceId=current_trace_id()
    )


@data_source_router.get("")
def data_sources(db: DbSession, user: CurrentUser) -> ApiResponse:
    if not has_permission(db, user, PERM_RETAIL_VIEW):
        raise AppError("FORBIDDEN", "需要 retail.view 权限", 403)
    return ApiResponse(
        data=service.data_sources(db, _owner(db, user)), traceId=current_trace_id()
    )


@data_source_router.get("/{source_id}/quality")
def data_source_quality(
    source_id: int, db: DbSession, user: CurrentUser
) -> ApiResponse:
    if not has_permission(db, user, PERM_RETAIL_VIEW):
        raise AppError("FORBIDDEN", "需要 retail.view 权限", 403)
    data = _safe(lambda: service.data_source_quality(db, _owner(db, user), source_id))
    return ApiResponse(data=data, traceId=current_trace_id())


@data_source_router.get("/{source_id}/preview")
def data_source_preview(
    source_id: int, db: DbSession, user: CurrentUser
) -> ApiResponse:
    if not has_permission(db, user, PERM_RETAIL_VIEW):
        raise AppError("FORBIDDEN", "需要 retail.view 权限", 403)
    data = _safe(lambda: service.data_source_preview(db, _owner(db, user), source_id))
    return ApiResponse(data=data, traceId=current_trace_id())


@router.post("/imports")
def import_retail_data(
    payload: ImportRequest, db: DbSession, user: CurrentUser
) -> ApiResponse:
    if user.role != "admin":
        raise AppError("FORBIDDEN", "仅平台管理员可以导入本地数据", 403)
    result = _safe(
        lambda: service.import_baskets(
            db, int(user.id), Path(payload.source_dir), payload.seed
        )
    )
    return ApiResponse(
        data={
            "importId": result.import_id,
            "rows": result.rows,
            "baskets": result.baskets,
            "products": result.products,
            "rules": result.rules,
            "reused": result.reused,
        },
        traceId=current_trace_id(),
    )


@router.post("/campaigns")
def create_campaign(
    payload: CampaignRequest, db: DbSession, user: CurrentUser
) -> ApiResponse:
    if not has_permission(db, user, PERM_CAMPAIGN_CREATE):
        raise AppError("FORBIDDEN", "需要 campaign.create 权限", 403)
    campaign = _safe(
        lambda: service.create_campaign(db, _owner(db, user), payload.rule_id)
    )
    return ApiResponse(
        data={"id": campaign.id, "name": campaign.name, "status": campaign.status},
        traceId=current_trace_id(),
    )


@router.get("/campaigns/{campaign_id}")
def campaign_detail(
    campaign_id: int, db: DbSession, user: CurrentUser
) -> ApiResponse:
    if not has_permission(db, user, PERM_RETAIL_VIEW):
        raise AppError("FORBIDDEN", "需要 retail.view 权限", 403)
    data = _safe(
        lambda: service.campaign_detail(db, _owner(db, user), campaign_id)
    )
    return ApiResponse(data=data, traceId=current_trace_id())


@router.post("/campaigns/{campaign_id}/transition")
def transition_campaign(
    campaign_id: int,
    payload: CampaignTransitionRequest,
    db: DbSession,
    user: CurrentUser,
) -> ApiResponse:
    if payload.action in {"confirm", "reject"} and not has_permission(
        db, user, PERM_CAMPAIGN_CONFIRM
    ):
        raise AppError("FORBIDDEN", "需要 campaign.confirm 权限", 403)
    if payload.action == "publish" and not has_permission(
        db, user, PERM_CAMPAIGN_PUBLISH
    ):
        raise AppError("FORBIDDEN", "需要 campaign.publish 权限", 403)
    campaign = _safe(
        lambda: service.transition_campaign(
            db,
            _owner(db, user),
            campaign_id,
            payload.action,
            payload.expectedVersion,
            payload.reason,
        )
    )
    return ApiResponse(
        data={
            "id": campaign.id,
            "status": campaign.status,
            "lockVersion": campaign.lock_version,
        },
        traceId=current_trace_id(),
    )


@router.post("/optimization-tasks/{task_id}/transition")
def transition_task(
    task_id: int, payload: TaskTransitionRequest, db: DbSession, user: CurrentUser
) -> ApiResponse:
    if not has_permission(db, user, PERM_TASK_UPDATE):
        raise AppError("FORBIDDEN", "需要 task.update 权限", 403)
    task = _safe(
        lambda: service.transition_task(
            db,
            _owner(db, user),
            task_id,
            payload.status,
            change_version=payload.changeVersion,
        )
    )
    return ApiResponse(
        data={"id": task.id, "status": task.status}, traceId=current_trace_id()
    )


@router.get("/optimization-tasks/{task_id}")
def task_detail(task_id: int, db: DbSession, user: CurrentUser) -> ApiResponse:
    if not has_permission(db, user, PERM_TASK_READ):
        raise AppError("FORBIDDEN", "需要 task.read 权限", 403)
    data = _safe(lambda: service.task_detail(db, _owner(db, user), task_id))
    return ApiResponse(data=data, traceId=current_trace_id())


@router.post("/optimization-tasks/{task_id}/assign")
def assign_task(
    task_id: int, payload: TaskAssignRequest, db: DbSession, user: CurrentUser
) -> ApiResponse:
    if not has_permission(db, user, PERM_TASK_UPDATE):
        raise AppError("FORBIDDEN", "需要 task.update 权限", 403)
    task = _safe(
        lambda: service.assign_task(
            db, _owner(db, user), task_id, payload.assignee_id
        )
    )
    return ApiResponse(
        data={"id": task.id, "assigneeId": task.assignee_id},
        traceId=current_trace_id(),
    )


@router.post("/optimization-tasks/{task_id}/verify")
def verify_task(task_id: int, db: DbSession, user: CurrentUser) -> ApiResponse:
    if not has_permission(db, user, PERM_TASK_UPDATE):
        raise AppError("FORBIDDEN", "需要 task.update 权限", 403)
    run = _safe(lambda: service.verify_task(db, _owner(db, user), task_id))
    return ApiResponse(
        data={
            "runId": run.id,
            "status": run.status,
            "taskId": task_id,
        },
        traceId=current_trace_id(),
    )


@router.post("/optimization-tasks/sync-from-evaluations")
def sync_failed_evaluations(db: DbSession, user: CurrentUser) -> ApiResponse:
    if not has_permission(db, user, PERM_TASK_UPDATE):
        raise AppError("FORBIDDEN", "需要 task.update 权限", 403)
    created = _safe(
        lambda: service.sync_failed_evaluations(db, _owner(db, user))
    )
    return ApiResponse(data={"created": created}, traceId=current_trace_id())


@router.get("/reports/weekly")
def weekly_report(db: DbSession, user: CurrentUser) -> ApiResponse:
    if not has_permission(db, user, PERM_RETAIL_VIEW):
        raise AppError("FORBIDDEN", "需要 retail.view 权限", 403)
    content = _safe(lambda: service.report(db, _owner(db, user)))
    return ApiResponse(
        data={"filename": "instant-retail-weekly-report.md", "content": content},
        traceId=current_trace_id(),
    )
