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


def get_current_user(request: Request, token: Annotated[str, Depends(oauth2_scheme)]) -> User:
    """返回当前登录用户对象 (校验存在与激活)"""
    container = request.app.state.container
    user_id = container.auth.decode_user_id(token)
    with container.database.session_factory() as db:
        user = container.user_repository.get(db, user_id)
        if not user or not user.is_active:
            raise AppError("USER_NOT_FOUND", "用户不存在或已停用", 401)
        return user


def get_current_user_id(
    request: Request, token: Annotated[str, Depends(oauth2_scheme)]
) -> int:
    container = request.app.state.container
    user_id = container.auth.decode_user_id(token)
    with container.database.session_factory() as db:
        user = container.user_repository.get(db, user_id)
        if not user or not user.is_active:
            raise AppError("USER_NOT_FOUND", "用户不存在或已停用", 401)
    return user_id


def get_current_admin(user: Annotated[Any, Depends(get_current_user)]) -> User:
    """管理员权限依赖: 非 admin 角色一律 403"""
    if user.role != "admin":
        raise AppError("FORBIDDEN", "需要管理员权限", 403)
    return user


DbSession = Annotated[Session, Depends(get_db)]
CurrentUserId = Annotated[int, Depends(get_current_user_id)]
# 注: 依赖类型用 Any 而非 User, 避免 FastAPI 为 ORM 模型生成 pydantic schema
# (SQLAlchemy 模型的 ForwardRef 注解会导致 openapi 生成失败)
CurrentUser = Annotated[Any, Depends(get_current_user)]
CurrentAdmin = Annotated[Any, Depends(get_current_admin)]
