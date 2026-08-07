from __future__ import annotations

import os
from pathlib import Path

from fastapi import UploadFile

from app.framework.errors import AppError


SUPPORTED_DOCUMENT_EXTENSIONS = frozenset({".txt", ".md", ".markdown", ".pdf", ".docx"})
DEFAULT_MAX_UPLOAD_BYTES = 50 * 1024 * 1024


def max_upload_bytes() -> int:
    return int(os.getenv("MAX_UPLOAD_FILE_SIZE", str(DEFAULT_MAX_UPLOAD_BYTES)))


def validate_upload(file: UploadFile) -> str:
    safe_name = Path(file.filename or "document").name
    extension = Path(safe_name).suffix.lower()
    if extension not in SUPPORTED_DOCUMENT_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_DOCUMENT_EXTENSIONS))
        raise AppError(
            "UNSUPPORTED_DOCUMENT_TYPE",
            f"不支持该文件格式，当前支持：{supported}",
            415,
            {"extension": extension or None, "supported": sorted(SUPPORTED_DOCUMENT_EXTENSIONS)},
        )
    return safe_name


async def save_upload(file: UploadFile, target: Path) -> int:
    limit = max_upload_bytes()
    size = 0
    try:
        with target.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise AppError(
                        "UPLOAD_TOO_LARGE",
                        f"上传文件超过 {limit // 1024 // 1024}MB 限制",
                        413,
                        {"maxBytes": limit},
                    )
                output.write(chunk)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    finally:
        await file.close()
    return size
