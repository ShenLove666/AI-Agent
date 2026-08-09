from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.framework.errors import AppError
from app.modules.users.models import User


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def get_container(request: Request):
    return request.app.state.container


def get_db(request: Request):
    yield from request.app.state.container.database.session()


def get_current_user(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    token: Annotated[str, Depends(oauth2_scheme)],
) -> User:
    """Return an active user attached to the request database session."""
    container = request.app.state.container
    user_id = container.auth.decode_user_id(token)
    user = container.user_repository.get(db, user_id)
    if not user or not user.is_active:
        raise AppError("USER_NOT_FOUND", "用户不存在或已停用", 401)
    return user


def get_current_user_id(user: Annotated[Any, Depends(get_current_user)]) -> int:
    return int(user.id)


def get_current_admin(user: Annotated[Any, Depends(get_current_user)]) -> User:
    if user.role != "admin":
        raise AppError("FORBIDDEN", "需要管理员权限", 403)
    return user


def get_current_supervisor(user: Annotated[Any, Depends(get_current_user)]) -> User:
    """客服主管或管理员：可访问主管队列与升级处理。"""
    if user.role not in {"supervisor", "admin"}:
        raise AppError("FORBIDDEN", "需要客服主管或管理员权限", 403)
    return user


DbSession = Annotated[Session, Depends(get_db)]
CurrentUserId = Annotated[int, Depends(get_current_user_id)]
CurrentUser = Annotated[Any, Depends(get_current_user)]
CurrentAdmin = Annotated[Any, Depends(get_current_admin)]
CurrentSupervisor = Annotated[Any, Depends(get_current_supervisor)]
