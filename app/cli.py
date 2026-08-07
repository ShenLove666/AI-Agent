"""命令行工具: uv run python -m app.cli <command>

用法:
    uv run python -m app.cli create-admin --username admin --password <密码>
    uv run python -m app.cli create-admin --username admin   # 交互式输入密码

用途: 首次部署时初始化管理员账号 (RAGent 登录页没有注册入口)。
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from dataclasses import asdict
from pathlib import Path

from app.application_core import build_container
from app.framework.config import Settings, settings
from app.framework.database import Database
from app.framework.migrations import upgrade_database
from app.modules.demo.service import DemoSeedError, DemoSeedService
from app.modules.commerce.service import RetailDataError, RetailService
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


def _print_counts(prefix: str, result) -> None:
    rendered = " ".join(f"{key}={value}" for key, value in asdict(result).items())
    print(f"[{prefix}] {rendered}")


def _seed_demo(*, password_env: str, reset: bool) -> int:
    password = os.getenv(password_env)
    if password is None:
        password = getpass.getpass("Demo password: ")
    if len(password) < 10:
        print("[error] Demo password must contain at least 10 characters.", file=sys.stderr)
        return 2

    container = build_container(Settings())
    try:
        upgrade_database(container.database)
        with container.database.session_factory() as db:
            try:
                demo_service = DemoSeedService(container)
                result = demo_service.seed(
                    db, password=password, reset=reset
                )
                user = UserRepository().get_by_username(db, demo_service.catalog.account.username)
                retail_results = RetailService().import_managed_snapshots(db, user.id)
                created_grounded, reused_grounded = demo_service.expand_grounded_support(db, target_cases=360)
            except (DemoSeedError, RetailDataError) as exc:
                print(f"[error] {exc}", file=sys.stderr)
                return 1
        _print_counts("seed-demo", result)
        print(
            "[retail-snapshots] "
            + " ".join(f"{item.rows}rows/{item.baskets}baskets/reused={item.reused}" for item in retail_results)
        )
        print(f"[grounded-support] created={created_grounded} reused={reused_grounded} total=360")
        return 0
    finally:
        container.database.engine.dispose()


def _clear_demo(*, yes: bool) -> int:
    if not yes:
        if not sys.stdin.isatty():
            print(
                "[error] clear-demo requires --yes in non-interactive mode.",
                file=sys.stderr,
            )
            return 2
        confirmation = input("Remove all demo-owned data? [y/N] ").strip().lower()
        if confirmation not in {"y", "yes"}:
            print("[clear-demo] cancelled")
            return 1

    container = build_container(Settings())
    try:
        upgrade_database(container.database)
        with container.database.session_factory() as db:
            try:
                result = DemoSeedService(container).clear(db)
            except DemoSeedError as exc:
                print(f"[error] {exc}", file=sys.stderr)
                return 1
        _print_counts("clear-demo", result)
        print(
            f"[clear-demo] removed_records={result.removed_records} "
            f"removed_files={result.removed_files}"
        )
        if result.external_cleanup_errors:
            for message in result.external_cleanup_errors:
                print(f"[warning] {message}", file=sys.stderr)
            return 1
        return 0
    finally:
        container.database.engine.dispose()


def _import_retail(*, source_dir: str, owner: str, seed: int) -> int:
    database = Database(Settings().database_url)
    try:
        upgrade_database(database)
        with database.session_factory() as db:
            user = UserRepository().get_by_username(db, owner)
            if not user:
                print(f"[error] User '{owner}' does not exist.", file=sys.stderr)
                return 2
            try:
                result = RetailService().import_baskets(db, user.id, source_dir=Path(source_dir), seed=seed)
            except (RetailDataError, OSError) as exc:
                db.rollback()
                print(f"[error] {exc}", file=sys.stderr)
                return 1
        print(f"[retail] rows={result.rows} baskets={result.baskets} products={result.products} rules={result.rules} reused={result.reused}")
        return 0
    finally:
        database.engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="RAGent Python CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    admin = sub.add_parser("create-admin", help="创建管理员账号")
    admin.add_argument("--username", default="admin", help="管理员用户名")
    admin.add_argument("--password", help="密码 (不传则交互输入)")
    admin.set_defaults(func=lambda args: create_admin(args.username, args.password or getpass.getpass("密码: ")))

    promote = sub.add_parser("promote-admin", help="将现有用户提升为管理员")
    promote.add_argument("--username", required=True, help="要提升的用户名")
    promote.set_defaults(func=lambda args: promote_admin(args.username))

    seed = sub.add_parser("seed-demo", help="创建或复用离线演示数据")
    seed.add_argument("--reset", action="store_true", help="先安全清理演示数据")
    seed.add_argument(
        "--password-env",
        default="DEMO_SEED_PASSWORD",
        help="读取演示密码的环境变量名",
    )
    seed.set_defaults(
        func=lambda args: _seed_demo(
            password_env=args.password_env, reset=args.reset
        )
    )

    clear = sub.add_parser("clear-demo", help="清理仅由演示账号拥有的数据")
    clear.add_argument(
        "--yes", action="store_true", help="非交互模式下确认执行清理"
    )
    clear.set_defaults(func=lambda args: _clear_demo(yes=args.yes))

    retail = sub.add_parser("seed-retail", help="导入购物篮并创建即时零售运营演示")
    retail.add_argument("--source-dir", required=True, help="包含 GoodsOrder.csv 与 GoodsTypes.csv 的目录")
    retail.add_argument("--owner", default="demo-admin", help="演示数据所属账号")
    retail.add_argument("--seed", type=int, default=20260807, help="确定性模拟数据种子")
    retail.set_defaults(func=lambda args: _import_retail(source_dir=args.source_dir, owner=args.owner, seed=args.seed))

    args = parser.parse_args(argv)
    result = args.func(args)
    return result if isinstance(result, int) else 0


if __name__ == "__main__":
    raise SystemExit(main())
