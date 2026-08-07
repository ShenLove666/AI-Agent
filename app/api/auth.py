from fastapi import APIRouter, Request

from app.api.dependencies import CurrentUser, DbSession
from app.framework.response import ApiResponse
from app.framework.trace import current_trace_id
from app.modules.users.schemas import LoginRequest, RegisterRequest


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=ApiResponse, status_code=201)
def register(payload: RegisterRequest, db: DbSession, request: Request) -> ApiResponse:
    user = request.app.state.container.auth.register(db, payload)
    return ApiResponse(
        data={"id": user.id, "username": user.username, "role": user.role},
        traceId=current_trace_id(),
    )


@router.post("/login", response_model=ApiResponse)
def login(payload: LoginRequest, db: DbSession, request: Request) -> ApiResponse:
    token = request.app.state.container.auth.login(db, payload)
    return ApiResponse(data=token.model_dump(), traceId=current_trace_id())


@router.get("/me", response_model=ApiResponse)
def current_user(user: CurrentUser) -> ApiResponse:
    """以数据库实时角色为准，避免前端长期信任过期的本地用户快照。"""
    return ApiResponse(
        data={
            "userId": str(user.id),
            "username": user.username,
            "role": user.role,
            "avatar": None,
        },
        traceId=current_trace_id(),
    )
