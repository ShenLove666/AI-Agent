from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ApiResponse(BaseModel):
    success: bool = True
    data: Any = None
    error: dict[str, Any] | None = None
    trace_id: str | None = Field(default=None, alias="traceId")
