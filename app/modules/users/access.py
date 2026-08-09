"""角色权限解析与商家数据范围。

权限完全由全局角色（users_v2.role）派生：user/supervisor/operator/admin。
组织成员关系（organization_members）只决定数据范围：
- 成员 → 组织 owner_user_id 的商家数据；
- 无成员（含未绑定组织的平台管理员）→ 只能看到自己名下的数据，
  不再隐式代理任何商家（替代旧的 owner_for 魔法）。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.users.models import Organization, OrganizationMember, User
from app.modules.users.permissions import ROLE_PERMISSIONS


def permissions_for(db: Session, user: User) -> frozenset[str]:
    """计算用户的权限集合：由全局角色决定。"""
    return ROLE_PERMISSIONS.get(user.role, frozenset())


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
