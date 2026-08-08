from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.dependencies import CurrentUser, DbSession
from app.framework.errors import AppError
from app.framework.response import ApiResponse
from app.framework.trace import current_trace_id
from app.modules.commerce.service import RetailDataError, RetailService


router = APIRouter(prefix="/retail", tags=["instant-retail"])
data_source_router = APIRouter(prefix="/data-sources", tags=["data-provenance"])
service = RetailService()


def _owner(db, user) -> int:
    return service.owner_for(db, user)


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


class TaskTransitionRequest(BaseModel):
    status: str


@router.get("/overview")
def retail_overview(db: DbSession, user: CurrentUser) -> ApiResponse:
    return ApiResponse(
        data=service.overview(db, _owner(db, user)), traceId=current_trace_id()
    )


@router.get("/data-sources")
def retail_data_sources(db: DbSession, user: CurrentUser) -> ApiResponse:
    return ApiResponse(
        data=service.data_sources(db, _owner(db, user)), traceId=current_trace_id()
    )


@data_source_router.get("")
def data_sources(db: DbSession, user: CurrentUser) -> ApiResponse:
    return ApiResponse(
        data=service.data_sources(db, _owner(db, user)), traceId=current_trace_id()
    )


@data_source_router.get("/{source_id}/quality")
def data_source_quality(
    source_id: int, db: DbSession, user: CurrentUser
) -> ApiResponse:
    data = _safe(lambda: service.data_source_quality(db, _owner(db, user), source_id))
    return ApiResponse(data=data, traceId=current_trace_id())


@data_source_router.get("/{source_id}/preview")
def data_source_preview(
    source_id: int, db: DbSession, user: CurrentUser
) -> ApiResponse:
    data = _safe(lambda: service.data_source_preview(db, _owner(db, user), source_id))
    return ApiResponse(data=data, traceId=current_trace_id())


@router.post("/imports")
def import_retail_data(
    payload: ImportRequest, db: DbSession, user: CurrentUser
) -> ApiResponse:
    if user.role != "admin":
        raise AppError("FORBIDDEN", "仅管理员可以导入本地数据", 403)
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
    campaign = _safe(
        lambda: service.create_campaign(db, _owner(db, user), payload.rule_id)
    )
    return ApiResponse(
        data={"id": campaign.id, "name": campaign.name, "status": campaign.status},
        traceId=current_trace_id(),
    )


@router.post("/optimization-tasks/{task_id}/transition")
def transition_task(
    task_id: int, payload: TaskTransitionRequest, db: DbSession, user: CurrentUser
) -> ApiResponse:
    task = _safe(
        lambda: service.transition_task(db, _owner(db, user), task_id, payload.status)
    )
    return ApiResponse(
        data={"id": task.id, "status": task.status}, traceId=current_trace_id()
    )


@router.get("/reports/weekly")
def weekly_report(db: DbSession, user: CurrentUser) -> ApiResponse:
    content = _safe(lambda: service.report(db, _owner(db, user)))
    return ApiResponse(
        data={"filename": "instant-retail-weekly-report.md", "content": content},
        traceId=current_trace_id(),
    )
