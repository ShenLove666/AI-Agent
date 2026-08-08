from __future__ import annotations

from fastapi import APIRouter

from app.api.dependencies import CurrentUser, DbSession
from app.framework.response import ApiResponse
from app.framework.trace import current_trace_id
from app.modules.orders.service import OrderService


router = APIRouter(prefix="/orders", tags=["commerce-orders"])
service = OrderService()


@router.get("/{order_no}")
def order_detail(order_no: str, db: DbSession, user: CurrentUser) -> ApiResponse:
    return ApiResponse(
        data=service.detail(db, int(user.id), order_no),
        traceId=current_trace_id(),
    )
