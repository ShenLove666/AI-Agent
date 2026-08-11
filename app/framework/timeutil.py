"""时间工具：统一 UTC 序列化。

数据库中的时间戳由 `datetime.utcnow()` 生成，是**没有时区信息的 naive UTC**。
若直接 `isoformat()` 输出（如 `2026-08-11T06:29:00`），前端 `new Date(value)`
会按本地时区解析，UTC+8 环境下正好差 8 小时。所有对外时间序列化必须走
`utc_iso()`：补上 UTC 时区并以 `Z` 结尾，浏览器按 UTC 正确解析。
"""

from __future__ import annotations

from datetime import datetime, timezone


def utc_iso(value: datetime | None) -> str | None:
    """把 naive/aware datetime 序列化为带 Z 的 UTC ISO 字符串（毫秒精度）。"""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )
