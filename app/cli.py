"""命令行工具: uv run python -m app.cli <command>

用法:
    uv run python -m app.cli create-admin --username admin --password <密码>
    uv run python -m app.cli create-admin --username admin   # 交互式输入密码

用途: 首次部署时初始化管理员账号 (RAGent 登录页没有注册入口)。
"""

from __future__ import annotations

import argparse
import getpass
import sys

from app.framework.config import settings
from app.framework.database import Database
from app.modules.users.models import User
from app.modules.users.repository import UserRepository


def create_admin(username: str, password: str) -> None:
    database = Database(settings.database_url)
    database.create_schema()
    repository = UserRepository()
    # 复用 AuthService 的密码哈希上下文
    from app.modules.users.service import AuthService

    passwords = AuthService(repository).passwords

    with database.session_factory() as db:
        if repository.get_by_username(db, username):
            print(f"[错误] 用户名 '{username}' 已存在，未创建。")
            sys.exit(1)
        user = User(
            username=username,
            password_hash=passwords.hash(password),
            role="admin",
        )
        db.add(user)
        db.commit()
        print(f"[完成] 管理员 '{username}' 创建成功 (role=admin)。")


def promote_admin(username: str) -> None:
    """由拥有服务器文件权限的运维人员显式提升现有账号。"""
    database = Database(settings.database_url)
    database.create_schema()
    repository = UserRepository()
    with database.session_factory() as db:
        user = repository.get_by_username(db, username)
        if not user:
            print(f"[错误] 用户名 '{username}' 不存在。")
            sys.exit(1)
        if user.role == "admin":
            print(f"[完成] 用户 '{username}' 已经是管理员，无需修改。")
            return
        user.role = "admin"
        db.commit()
        print(f"[完成] 用户 '{username}' 已提升为管理员 (role=admin)，请重新登录。")


def main() -> None:
    parser = argparse.ArgumentParser(description="RAGent Python CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    admin = sub.add_parser("create-admin", help="创建管理员账号")
    admin.add_argument("--username", default="admin", help="管理员用户名")
    admin.add_argument("--password", help="密码 (不传则交互输入)")
    admin.set_defaults(func=lambda args: create_admin(args.username, args.password or getpass.getpass("密码: ")))

    promote = sub.add_parser("promote-admin", help="将现有用户提升为管理员")
    promote.add_argument("--username", required=True, help="要提升的用户名")
    promote.set_defaults(func=lambda args: promote_admin(args.username))

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
