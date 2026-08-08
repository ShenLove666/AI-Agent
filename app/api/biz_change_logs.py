"""业务变更审计日志：基于现有 SupportEvent 事件流实现。

前端 BizChangeLogPage 期望通用审计日志格式；本模块将客服/知识域
的真实事件（SupportEvent）映射为统一审计视图，避免 501 NOT_IMPLEMENTED。
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.api.dependencies import CurrentUser, DbSession
from app.framework.response import ApiResponse
from app.framework.trace import current_trace_id
from app.modules.support.models import SupportEvent
from app.modules.users.models import User

router = APIRouter(prefix="/biz-change-logs", tags=["biz-change-logs"])

# 事件类型 -> (业务类型, 操作类型) 映射
_EVENT_MAP: dict[str, tuple[str, str]] = {
    "case_created": ("SUPPORT_CASE", "CREATE"),
    "case_transitioned": ("SUPPORT_CASE", "UPDATE"),
    "case_assigned": ("SUPPORT_CASE", "UPDATE"),
    "case_labels_updated": ("SUPPORT_CASE", "UPDATE"),
    "case_escalated": ("SUPPORT_CASE", "UPDATE"),
    "escalation_accepted": ("SUPPORT_CASE", "UPDATE"),
    "escalation_resolved": ("SUPPORT_CASE", "UPDATE"),
    "escalation_returned": ("SUPPORT_CASE", "UPDATE"),
    "suggestion_generated": ("SUPPORT_CASE", "RUN"),
    "suggestion_accepted": ("SUPPORT_CASE", "UPDATE"),
    "suggestion_edited": ("SUPPORT_CASE", "UPDATE"),
    "suggestion_rejected": ("SUPPORT_CASE", "UPDATE"),
    "suggestion_escalated": ("SUPPORT_CASE", "UPDATE"),
    "outbound_sent": ("SUPPORT_CASE", "RUN"),
    "outbound_delivered": ("SUPPORT_CASE", "RUN"),
    "knowledge_release_published": ("KNOWLEDGE_BASE", "CREATE"),
    "knowledge_release_activated": ("KNOWLEDGE_BASE", "UPDATE"),
    "knowledge_gap_resolved": ("KNOWLEDGE_DOCUMENT", "UPDATE"),
}


def _parse_payload(raw: str) -> dict:
    import json

    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


@router.get("")
def list_change_logs(
    db: DbSession,
    user: CurrentUser,
    current: int = Query(default=1, ge=1),
    size: int = Query(default=10, ge=1, le=100),
    bizType: str | None = None,
    operationType: str | None = None,
    success: bool | None = None,
) -> ApiResponse:
    statement = select(SupportEvent, User.username).outerjoin(
        User, User.id == SupportEvent.actor_id
    )
    # 非管理员只看自己 owner 的事件
    if user.role != "admin":
        statement = statement.where(SupportEvent.owner_id == user.id)
    if bizType:
        statement = statement.where(
            SupportEvent.event_type.in_(
                [key for key, (b, _) in _EVENT_MAP.items() if b == bizType]
            )
        )
    if operationType:
        statement = statement.where(
            SupportEvent.event_type.in_(
                [key for key, (_, o) in _EVENT_MAP.items() if o == operationType]
            )
        )
    total = db.scalar(
        select(func.count()).select_from(statement.subquery())
    ) or 0
    rows = list(
        db.execute(
            statement.order_by(SupportEvent.occurred_at.desc())
            .offset((current - 1) * size)
            .limit(size)
        ).all()
    )
    records = []
    for event, operator_name in rows:
        biz_type, op_type = _EVENT_MAP.get(
            event.event_type, ("SUPPORT_CASE", "RUN")
        )
        payload = _parse_payload(event.payload_json)
        action_desc = str(
            payload.get("reason")
            or payload.get("note")
            or event.event_type
        )[:200]
        after_snapshot = (
            f"caseId={event.case_id} " + " ".join(
                f"{k}={v}" for k, v in list(payload.items())[:4]
            )
        ).strip()
        records.append(
            {
                "id": str(event.id),
                "bizType": biz_type,
                "bizId": str(event.case_id),
                "operationType": op_type,
                "actionDesc": action_desc,
                "beforeSnapshot": None,
                "afterSnapshot": after_snapshot or None,
                "changeDiff": None,
                "operatorId": str(event.actor_id) if event.actor_id else None,
                "operatorName": operator_name,
                "operatorRole": "admin" if user.role == "admin" else "user",
                "success": True,
                "errorMessage": None,
                "className": "SupportEvent",
                "methodName": event.event_type,
                "ip": None,
                "userAgent": None,
                "createTime": event.occurred_at.isoformat(),
            }
        )
    return ApiResponse(
        data={
            "records": records,
            "total": total,
            "size": size,
            "current": current,
            "pages": (total + size - 1) // size if size else 0,
        },
        traceId=current_trace_id(),
    )


@router.get("/{log_id}")
def change_log_detail(log_id: int, db: DbSession, user: CurrentUser) -> ApiResponse:
    row = db.execute(
        select(SupportEvent, User.username)
        .outerjoin(User, User.id == SupportEvent.actor_id)
        .where(SupportEvent.id == log_id)
    ).first()
    if row is None or (user.role != "admin" and row[0].owner_id != user.id):
        return ApiResponse(data=None, traceId=current_trace_id())
    event, operator_name = row
    biz_type, op_type = _EVENT_MAP.get(event.event_type, ("SUPPORT_CASE", "RUN"))
    payload = _parse_payload(event.payload_json)
    return ApiResponse(
        data={
            "id": str(event.id),
            "bizType": biz_type,
            "bizId": str(event.case_id),
            "operationType": op_type,
            "actionDesc": str(
                payload.get("reason") or payload.get("note") or event.event_type
            )[:200],
            "beforeSnapshot": None,
            "afterSnapshot": _parse_payload(event.payload_json),
            "changeDiff": None,
            "operatorId": str(event.actor_id) if event.actor_id else None,
            "operatorName": operator_name,
            "operatorRole": "admin" if user.role == "admin" else "user",
            "success": True,
            "errorMessage": None,
            "className": "SupportEvent",
            "methodName": event.event_type,
            "ip": None,
            "userAgent": None,
            "createTime": event.occurred_at.isoformat(),
        },
        traceId=current_trace_id(),
    )
