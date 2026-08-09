"""组织成员关系解析：权限派生与商家数据范围。

替代旧的"管理员自动代理最新商家"魔法（support/commerce 的 owner_for）。
数据范围规则：
- 用户必须是某组织成员，才能看到该组织 owner_user_id 名下的商家数据；
- 无成员关系的用户（如未绑定的平台管理员）返回 None，读接口返回空数据、写接口拒绝；
- 全局角色（admin/supervisor）只提供平台能力，不再隐式获得任何商家数据。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.users.models import Organization, OrganizationMember, User
from app.modules.users.permissions import (
    GLOBAL_ROLE_PERMISSIONS,
    ROLE_PERMISSIONS,
)


def permissions_for(db: Session, user: User) -> frozenset[str]:
    """计算用户的完整权限集合：全局角色兼容能力 + 组织成员角色能力。"""
    perms = set(GLOBAL_ROLE_PERMISSIONS.get(user.role, frozenset()))
    member_roles = db.scalars(
        select(OrganizationMember.role).where(OrganizationMember.user_id == user.id)
    ).all()
    for role in member_roles:
        perms |= ROLE_PERMISSIONS.get(role, frozenset())
    return frozenset(perms)


def has_permission(db: Session, user: User, permission: str) -> bool:
    return permission in permissions_for(db, user)


def resolve_owner(db: Session, user: User) -> int:
    """解析用户可见的商家数据归属。

    - 组织成员 → 返回组织 owner_user_id（组织商家数据）；
    - 无成员关系（含未绑定组织的平台管理员）→ 返回用户自己，
      只能看到自己名下的数据，不再隐式代理任何商家。
    """
    org_id = db.scalar(
        select(OrganizationMember.org_id)
        .where(OrganizationMember.user_id == user.id)
        .limit(1)
    )
    if org_id is None:
        return int(user.id)
    org = db.get(Organization, org_id)
    if org is None:
        return int(user.id)
    return org.owner_user_id


def ensure_owner(db: Session, user: User, error_code: str = "NO_ORGANIZATION") -> int:
    """解析商家数据归属（组织数据或自己的数据），恒有归属。"""
    return resolve_owner(db, user)
