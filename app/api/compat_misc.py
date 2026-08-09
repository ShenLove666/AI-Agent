"""RAGent 前端契约兼容路由: 用户管理 / 系统设置 / 未实现模块 501 兜底

原则 (审计文档 P0-1):
- 已实现模块提供真实接口;
- 暂不实现的模块返回结构化 501 NOT_IMPLEMENTED, 不允许用静态假数据冒充;
- 所有管理接口必须 admin 权限。
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.dependencies import CurrentAdmin, CurrentUser, DbSession
from app.framework.errors import AppError
from app.framework.response import ApiResponse
from app.framework.trace import current_trace_id
from app.modules.users.models import User
from app.modules.users.permissions import VALID_ROLES
from app.modules.users.service import AuthService


router = APIRouter(prefix="", tags=["misc-compat"])


# ---------------------------------------------------------------------------
# 用户管理 (P0-4: 管理员创建/修改用户)
# ---------------------------------------------------------------------------


def user_vo(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "enabled": user.is_active,
        "createTime": user.created_at.isoformat() if user.created_at else None,
        "updateTime": user.updated_at.isoformat() if user.updated_at else None,
    }


class UserCreateRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=8, max_length=128)
    email: str | None = None
    role: str = Field(default="user", pattern="^(" + "|".join(sorted(VALID_ROLES)) + ")$")


class UserUpdateRequest(BaseModel):
    email: str | None = None
    role: str | None = Field(default=None, pattern="^(" + "|".join(sorted(VALID_ROLES)) + ")$")
    enabled: bool | None = None


class PasswordChangeRequest(BaseModel):
    currentPassword: str
    newPassword: str = Field(min_length=8, max_length=128)


@router.get("/users", response_model=ApiResponse)
def list_users(
    db: DbSession,
    admin: CurrentAdmin,
    request: Request,
    current: int = 1,
    size: int = 10,
    keyword: str | None = None,
) -> ApiResponse:
    statement = select(User)
    if keyword:
        statement = statement.where(User.username.like(f"%{keyword}%"))
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    items = list(
        db.scalars(
            statement.order_by(User.created_at.desc())
            .offset((max(current, 1) - 1) * max(size, 1))
            .limit(min(max(size, 1), 100))
        )
    )
    return ApiResponse(
        data={
            "records": [user_vo(item) for item in items],
            "total": total,
            "size": size,
            "current": current,
            "pages": (total + size - 1) // size if size else 0,
        },
        traceId=current_trace_id(),
    )


@router.post("/users", response_model=ApiResponse)
def create_user(
    payload: UserCreateRequest,
    db: DbSession,
    admin: CurrentAdmin,
    request: Request,
) -> ApiResponse:
    container = request.app.state.container
    if container.user_repository.get_by_username(db, payload.username):
        raise AppError("USERNAME_EXISTS", "用户名已存在", 409)
    passwords = AuthService(container.user_repository).passwords
    user = User(
        username=payload.username,
        password_hash=passwords.hash(payload.password),
        email=payload.email,
        role=payload.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return ApiResponse(data=user_vo(user), traceId=current_trace_id())


@router.put("/users/{user_id}", response_model=ApiResponse)
def update_user(
    user_id: int,
    payload: UserUpdateRequest,
    db: DbSession,
    admin: CurrentAdmin,
    request: Request,
) -> ApiResponse:
    user = db.get(User, user_id)
    if not user:
        raise AppError("USER_NOT_FOUND", "用户不存在", 404)
    if payload.email is not None:
        user.email = payload.email
    if payload.role is not None:
        user.role = payload.role
    if payload.enabled is not None:
        user.is_active = payload.enabled
    db.commit()
    db.refresh(user)
    return ApiResponse(data=user_vo(user), traceId=current_trace_id())


@router.delete("/users/{user_id}", response_model=ApiResponse)
def delete_user(
    user_id: int, db: DbSession, admin: CurrentAdmin, request: Request
) -> ApiResponse:
    user = db.get(User, user_id)
    if not user:
        raise AppError("USER_NOT_FOUND", "用户不存在", 404)
    if user.id == admin.id:
        raise AppError("FORBIDDEN", "不能停用当前登录的管理员", 400)
    user.is_active = False
    db.commit()
    return ApiResponse(data=True, traceId=current_trace_id())


@router.put("/user/password", response_model=ApiResponse)
def change_password(
    payload: PasswordChangeRequest,
    db: DbSession,
    user: CurrentUser,
    request: Request,
) -> ApiResponse:
    container = request.app.state.container
    passwords = AuthService(container.user_repository).passwords
    if not passwords.verify(payload.currentPassword, user.password_hash):
        raise AppError("INVALID_CREDENTIALS", "当前密码不正确", 400)
    user.password_hash = passwords.hash(payload.newPassword)
    db.commit()
    return ApiResponse(data=True, traceId=current_trace_id())





# ---------------------------------------------------------------------------
# 未实现模块: 结构化 501 (禁止静态假数据)
# ---------------------------------------------------------------------------


def _not_implemented(module: str) -> ApiResponse:
    return ApiResponse(
        success=False,
        data=None,
        error={
            "code": "NOT_IMPLEMENTED",
            "message": f"模块 '{module}' 尚未在 Python 后端实现",
            "module": module,
        },
        trace_id=current_trace_id(),
    )


_NOT_IMPLEMENTED_MODULES = [
    ("agents", "/agents"),
    ("dashboard", "/admin/dashboard"),
    ("ingestion-pipelines", "/ingestion/pipelines"),
    ("ingestion-tasks", "/ingestion/tasks"),
    ("intent-tree", "/intent-tree"),
    ("knowledge-graph", "/admin/kg"),
    ("query-term-mappings", "/mappings"),
    ("sample-questions", "/sample-questions"),
]


for _module_name, _prefix in _NOT_IMPLEMENTED_MODULES:

    @router.api_route(
        _prefix,
        methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        response_model=ApiResponse,
        include_in_schema=False,
    )
    async def _not_implemented_root(module_name: str = _module_name):
        return _not_implemented(module_name)

    @router.api_route(
        _prefix + "/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        response_model=ApiResponse,
        include_in_schema=False,
    )
    async def _not_implemented_handler(path: str, module_name: str = _module_name):
        return _not_implemented(module_name)
