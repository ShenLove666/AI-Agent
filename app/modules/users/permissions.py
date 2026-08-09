"""角色-权限能力模型。

组织成员通过 organization_members.role 获得商家域能力；
全局角色（users_v2.role）仅保留兼容层：admin 视作平台管理员，
supervisor 视作客服主管。权限判定永远以数据库实时数据为准。
"""

from __future__ import annotations

# 权限能力全集（业务模块在写接口中逐一校验）
PERM_SETTINGS_WRITE = "settings.write"  # 修改系统运行时配置
PERM_USER_MANAGE = "user.manage"  # 用户/成员管理
PERM_CAMPAIGN_CONFIRM = "campaign.confirm"  # 确认运营方案
PERM_CAMPAIGN_PUBLISH = "campaign.publish"  # 发布运营方案
PERM_EVALUATION_RUN = "evaluation.run"  # 发起评测
PERM_TASK_ASSIGN = "task.assign"  # 分派/流转优化任务
PERM_SUPPORT_RESOLVE = "support.resolve"  # 解决升级/质检
PERM_SUPPORT_CASE_WORK = "support.case.work"  # 处理工单
PERM_RETAIL_VIEW = "retail.view"  # 查看经营数据
PERM_PLATFORM_MANAGE = "platform.manage"  # 平台级管理（链路追踪/全局设置/全局用户）

ALL_PERMISSIONS = frozenset(
    {
        PERM_SETTINGS_WRITE,
        PERM_USER_MANAGE,
        PERM_CAMPAIGN_CONFIRM,
        PERM_CAMPAIGN_PUBLISH,
        PERM_EVALUATION_RUN,
        PERM_TASK_ASSIGN,
        PERM_SUPPORT_RESOLVE,
        PERM_SUPPORT_CASE_WORK,
        PERM_RETAIL_VIEW,
        PERM_PLATFORM_MANAGE,
    }
)

# 组织成员角色 → 权限集合
ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "platform_admin": ALL_PERMISSIONS,
    "merchant_owner": frozenset(
        {
            PERM_SETTINGS_WRITE,
            PERM_USER_MANAGE,
            PERM_CAMPAIGN_CONFIRM,
            PERM_CAMPAIGN_PUBLISH,
            PERM_EVALUATION_RUN,
            PERM_TASK_ASSIGN,
            PERM_SUPPORT_RESOLVE,
            PERM_SUPPORT_CASE_WORK,
            PERM_RETAIL_VIEW,
        }
    ),
    "operator": frozenset(
        {
            PERM_CAMPAIGN_CONFIRM,
            PERM_EVALUATION_RUN,
            PERM_TASK_ASSIGN,
            PERM_RETAIL_VIEW,
        }
    ),
    "support_supervisor": frozenset(
        {PERM_SUPPORT_RESOLVE, PERM_SUPPORT_CASE_WORK, PERM_RETAIL_VIEW}
    ),
    "support_agent": frozenset({PERM_SUPPORT_CASE_WORK}),
    "analyst": frozenset({PERM_RETAIL_VIEW}),
}

# 全局角色兼容映射（无组织成员时的兜底能力，不提供商家数据范围）
GLOBAL_ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "admin": ROLE_PERMISSIONS["platform_admin"],
    "supervisor": ROLE_PERMISSIONS["support_supervisor"],
    "user": frozenset(),
}

# 校验非法角色名
VALID_MEMBER_ROLES = frozenset(ROLE_PERMISSIONS)
