"""角色-权限模型（4 角色，客服域与经营域彻底切开）。

角色（users_v2.role 兼容名）：
- user       普通客服：只能处理客服工单，看不到经营域
- supervisor 客服主管：客服 + 升级处理 + 质量概览 + 评测只读
- operator   商家运营：只看经营域（经营数据/方案/任务），看不到客服
- admin      商家负责人/管理员：全部

组织成员关系（organization_members）只决定数据范围（resolve_owner），
权限完全由全局角色派生，避免成员角色膨胀。
"""

from __future__ import annotations

# ---- 客服域 ----
PERM_CASE_READ = "support.case.read"
PERM_CASE_REPLY = "support.case.reply"
PERM_CASE_RESOLVE = "support.case.resolve"
PERM_CASE_ESCALATE = "support.case.escalate"
PERM_ESCALATION_READ = "support.escalation.read"
PERM_ESCALATION_ACCEPT = "support.escalation.accept"
PERM_ESCALATION_RESOLVE = "support.escalation.resolve"
PERM_ESCALATION_RETURN = "support.escalation.return"
PERM_QUALITY_READ = "support.quality.read"

# ---- 经营域 ----
PERM_RETAIL_VIEW = "retail.view"
PERM_CAMPAIGN_CREATE = "campaign.create"
PERM_CAMPAIGN_CONFIRM = "campaign.confirm"
PERM_CAMPAIGN_PUBLISH = "campaign.publish"
PERM_TASK_READ = "task.read"
PERM_TASK_UPDATE = "task.update"

# ---- 平台域 ----
PERM_KNOWLEDGE_MANAGE = "knowledge.manage"
PERM_EVALUATION_READ = "evaluation.read"
PERM_EVALUATION_RUN = "evaluation.run"
PERM_SETTINGS_WRITE = "settings.write"
PERM_USER_MANAGE = "user.manage"

ALL_PERMISSIONS = frozenset(
    {
        PERM_CASE_READ,
        PERM_CASE_REPLY,
        PERM_CASE_RESOLVE,
        PERM_CASE_ESCALATE,
        PERM_ESCALATION_READ,
        PERM_ESCALATION_ACCEPT,
        PERM_ESCALATION_RESOLVE,
        PERM_ESCALATION_RETURN,
        PERM_QUALITY_READ,
        PERM_RETAIL_VIEW,
        PERM_CAMPAIGN_CREATE,
        PERM_CAMPAIGN_CONFIRM,
        PERM_CAMPAIGN_PUBLISH,
        PERM_TASK_READ,
        PERM_TASK_UPDATE,
        PERM_KNOWLEDGE_MANAGE,
        PERM_EVALUATION_READ,
        PERM_EVALUATION_RUN,
        PERM_SETTINGS_WRITE,
        PERM_USER_MANAGE,
    }
)

# 普通客服：只能处理工单，不能发起升级处理之外的动作
SUPPORT_AGENT_PERMISSIONS = frozenset(
    {
        PERM_CASE_READ,
        PERM_CASE_REPLY,
        PERM_CASE_RESOLVE,
        PERM_CASE_ESCALATE,
    }
)

# 客服主管：客服 + 升级全流程 + 质量概览 + 评测只读
SUPPORT_SUPERVISOR_PERMISSIONS = SUPPORT_AGENT_PERMISSIONS | frozenset(
    {
        PERM_ESCALATION_READ,
        PERM_ESCALATION_ACCEPT,
        PERM_ESCALATION_RESOLVE,
        PERM_ESCALATION_RETURN,
        PERM_QUALITY_READ,
        PERM_EVALUATION_READ,
    }
)

# 商家运营：只看经营域；确认方案但不可发布到外部（发布仅 admin）
OPERATOR_PERMISSIONS = frozenset(
    {
        PERM_RETAIL_VIEW,
        PERM_CAMPAIGN_CREATE,
        PERM_CAMPAIGN_CONFIRM,
        PERM_TASK_READ,
        PERM_TASK_UPDATE,
    }
)

# 全局角色 → 权限集合（后端 API 校验的唯一依据）
ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "user": SUPPORT_AGENT_PERMISSIONS,
    "supervisor": SUPPORT_SUPERVISOR_PERMISSIONS,
    "operator": OPERATOR_PERMISSIONS,
    "admin": ALL_PERMISSIONS,
}

# 校验非法角色名
VALID_ROLES = frozenset(ROLE_PERMISSIONS)
