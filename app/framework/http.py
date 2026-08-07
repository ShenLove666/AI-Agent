from __future__ import annotations

import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.framework.errors import AppError
from app.framework.trace import trace_id_var


def install_http_conventions(app: FastAPI) -> None:
    @app.middleware("http")
    async def trace_middleware(request: Request, call_next):
        trace_id = request.headers.get("X-Trace-Id") or uuid.uuid4().hex
        token = trace_id_var.set(trace_id)
        started_at = time.perf_counter()
        try:
            response = await call_next(request)
            response.headers["X-Trace-Id"] = trace_id
            response.headers["X-Elapsed-Ms"] = str(
                round((time.perf_counter() - started_at) * 1000, 2)
            )
            return response
        finally:
            trace_id_var.reset(token)

    @app.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "data": None,
                "error": {"code": exc.code, "message": exc.message, "details": exc.details},
                "traceId": trace_id_var.get(),
            },
        )
