from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class AppError(Exception):
    code: str
    message: str
    status_code: int = 400
    details: dict | None = None

    def __str__(self) -> str:
        return self.message


class ProviderUnavailableError(AppError):
    def __init__(self, message: str = "没有可用的模型服务", details: dict | None = None):
        super().__init__("MODEL_PROVIDER_UNAVAILABLE", message, 503, details)


class ModelStreamTimeoutError(AppError):
    def __init__(self, stage: str, timeout_seconds: float):
        labels = {"first_token": "首个 Token", "idle": "Token 间隔", "total": "总生成"}
        label = labels.get(stage, "流式生成")
        super().__init__(
            "MODEL_STREAM_TIMEOUT",
            f"{label}超时，请稍后重试",
            504,
            {"stage": stage, "timeoutSeconds": timeout_seconds},
        )


class RetrievalError(AppError):
    def __init__(self, message: str, details: dict | None = None):
        super().__init__("RETRIEVAL_FAILED", message, 502, details)
