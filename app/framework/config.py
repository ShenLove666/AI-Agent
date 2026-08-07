from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv


# override=True: 项目 .env 优先于系统环境变量
# (系统里可能残留旧的 DASHSCOPE_API_KEY 等变量, 不覆盖会导致模型调用 401)
load_dotenv(override=True)


def _csv(name: str, default: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in os.getenv(name, default).split(",") if item.strip())


@dataclass(frozen=True, slots=True)
class ModelEndpoint:
    name: str
    base_url: str
    api_key: str
    model: str
    reasoning_model: str | None = None
    priority: int = 100


@dataclass(frozen=True, slots=True)
class Settings:
    app_name: str = field(default_factory=lambda: os.getenv("APP_NAME", "RAGent Python"))
    environment: str = field(default_factory=lambda: os.getenv("APP_ENV", "development"))
    api_prefix: str = field(default_factory=lambda: os.getenv("API_PREFIX", "/api/v1"))
    database_url: str = field(
        default_factory=lambda: os.getenv("DB_URL", "sqlite:///./data/ragent.db")
    )
    cors_origins: tuple[str, ...] = field(
        default_factory=lambda: _csv("CORS_ORIGINS", "http://localhost:3000")
    )
    retrieval_timeout_seconds: float = field(
        default_factory=lambda: float(os.getenv("RETRIEVAL_TIMEOUT_SECONDS", "8"))
    )
    retrieval_candidate_limit: int = field(
        default_factory=lambda: int(os.getenv("RETRIEVAL_CANDIDATE_LIMIT", "20"))
    )
    retrieval_context_limit: int = field(
        default_factory=lambda: int(os.getenv("RETRIEVAL_CONTEXT_LIMIT", "6"))
    )
    prompt_history_token_budget: int = field(
        default_factory=lambda: int(os.getenv("PROMPT_HISTORY_TOKEN_BUDGET", "3000"))
    )
    prompt_context_token_budget: int = field(
        default_factory=lambda: int(os.getenv("PROMPT_CONTEXT_TOKEN_BUDGET", "4000"))
    )
    chat_timeout_seconds: float = field(
        default_factory=lambda: float(os.getenv("CHAT_TIMEOUT_SECONDS", "120"))
    )
    chat_first_token_timeout_seconds: float = field(
        default_factory=lambda: float(os.getenv("CHAT_FIRST_TOKEN_TIMEOUT_SECONDS", "20"))
    )
    chat_idle_timeout_seconds: float = field(
        default_factory=lambda: float(os.getenv("CHAT_IDLE_TIMEOUT_SECONDS", "30"))
    )
    circuit_failure_threshold: int = field(
        default_factory=lambda: int(os.getenv("CIRCUIT_FAILURE_THRESHOLD", "3"))
    )
    circuit_recovery_seconds: float = field(
        default_factory=lambda: float(os.getenv("CIRCUIT_RECOVERY_SECONDS", "30"))
    )

    def chat_endpoints(self) -> tuple[ModelEndpoint, ...]:
        endpoints: list[ModelEndpoint] = []

        mimo_key = os.getenv("MIMO_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
        if mimo_key:
            endpoints.append(
                ModelEndpoint(
                    name="mimo",
                    base_url=os.getenv("MIMO_BASE_URL")
                    or os.getenv("DASHSCOPE_BASE_URL", "https://api.xiaomimimo.com/v1"),
                    api_key=mimo_key,
                    model=os.getenv("MIMO_CHAT_MODEL")
                    or os.getenv("MIMO_MODEL")
                    or os.getenv("VISION_MODEL", "mimo-v2.5"),
                    reasoning_model=os.getenv("MIMO_REASONING_MODEL"),
                    priority=5,
                )
            )

        if key := os.getenv("DEEPSEEK_API_KEY"):
            endpoints.append(
                ModelEndpoint(
                    name="deepseek",
                    base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
                    api_key=key,
                    model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
                    reasoning_model=os.getenv(
                        "DEEPSEEK_REASONING_MODEL", "deepseek-v4-flash"
                    ),
                    priority=10,
                )
            )
        if key := os.getenv("BACKUP_LLM_API_KEY"):
            endpoints.append(
                ModelEndpoint(
                    name="backup",
                    base_url=os.environ["BACKUP_LLM_BASE_URL"],
                    api_key=key,
                    model=os.environ["BACKUP_LLM_MODEL"],
                    reasoning_model=os.getenv("BACKUP_LLM_REASONING_MODEL"),
                    priority=20,
                )
            )
        return tuple(sorted(endpoints, key=lambda endpoint: endpoint.priority))


settings = Settings()
