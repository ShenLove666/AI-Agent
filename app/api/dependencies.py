from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
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


def make_permission_requirement(permission: str):
    """按权限能力生成依赖：校验组织角色/全局角色派生的权限集合。"""

    def require(
        request: Request,
        db: Annotated[Session, Depends(get_db)],
        user: Annotated[Any, Depends(get_current_user)],
    ) -> User:
        from app.modules.users.access import has_permission

        if not has_permission(db, user, permission):
            raise AppError("FORBIDDEN", f"需要权限：{permission}", 403)
        return user

    return require


def get_current_permissions(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[Any, Depends(get_current_user)],
) -> frozenset[str]:
    from app.modules.users.access import permissions_for

    return permissions_for(db, user)


def get_current_org(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[Any, Depends(get_current_user)],
) -> dict | None:
    """当前用户的商家归属：{orgId, orgName, ownerUserId, role}；无成员返回 None。"""
    from app.modules.users.models import Organization, OrganizationMember

    membership = db.scalar(
        select(OrganizationMember)
        .where(OrganizationMember.user_id == user.id)
        .limit(1)
    )
    if membership is None:
        return None
    org = db.get(Organization, membership.org_id)
    if org is None:
        return None
    return {
        "orgId": org.id,
        "orgName": org.name,
        "ownerUserId": org.owner_user_id,
        "role": membership.role,
    }


DbSession = Annotated[Session, Depends(get_db)]
CurrentUserId = Annotated[int, Depends(get_current_user_id)]
CurrentUser = Annotated[Any, Depends(get_current_user)]
CurrentAdmin = Annotated[Any, Depends(get_current_admin)]
CurrentSupervisor = Annotated[Any, Depends(get_current_supervisor)]
CurrentPermissions = Annotated[frozenset[str], Depends(get_current_permissions)]
CurrentOrg = Annotated[dict | None, Depends(get_current_org)]
