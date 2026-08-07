from __future__ import annotations

from fastapi import FastAPI

from app.application_core import (
    ApplicationContainer,
    build_container,
    build_vector_components,
    create_app as _create_app,
)
from app.framework.config import Settings


def create_app(app_settings: Settings | None = None) -> FastAPI:
    """创建隔离的应用实例，并在未显式传参时重新读取当前环境配置。"""
    return _create_app(app_settings or Settings())


app = create_app()


__all__ = [
    "ApplicationContainer",
    "app",
    "build_container",
    "build_vector_components",
    "create_app",
]
