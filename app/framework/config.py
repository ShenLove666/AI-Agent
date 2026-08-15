from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv


# override=True: 项目 .env 优先于系统环境变量
# (系统里可能残留旧的 DASHSCOPE_API_KEY 等变量, 不覆盖会导致模型调用 401)
load_dotenv(override=True)


# This value is intentionally retained for development/test compatibility.  It
# must never be accepted by a production process: the authentication service
# uses the same environment variable when signing and verifying JWTs.
DEFAULT_JWT_SECRET = "change-me-before-production"
INSECURE_JWT_SECRETS = frozenset(
    {
        DEFAULT_JWT_SECRET,
        # Keep the committed template placeholder fail-fast as well; it is
        # long enough to pass a length-only check but is publicly known.
        "REPLACE_WITH_RANDOM_64_CHAR_SECRET",
    }
)
MIN_PRODUCTION_JWT_SECRET_LENGTH = 32
PRODUCTION_ENVIRONMENTS = frozenset({"prod", "production"})


def validate_jwt_secret(environment: str, secret: str | None = None) -> str:
    """Validate the JWT signing secret at application configuration time.

    Development keeps the historical fallback so local demos/tests remain
    self-contained.  Production must provide a non-default, sufficiently
    long secret with a little character diversity; otherwise startup fails
    before any request can be authenticated with a forgeable key.
    """

    value = secret if secret is not None else os.getenv("JWT_SECRET", DEFAULT_JWT_SECRET)
    normalized_environment = (environment or "").strip().lower()
    if normalized_environment in PRODUCTION_ENVIRONMENTS:
        distinct_characters = len(set(value))
        if (
            not value
            or value.strip() != value
            or value in INSECURE_JWT_SECRETS
            or len(value) < MIN_PRODUCTION_JWT_SECRET_LENGTH
            or distinct_characters < 8
        ):
            raise RuntimeError(
                "JWT_SECRET must be configured with at least 32 diverse characters "
                "when APP_ENV is production/prod"
            )
    return value


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
        default_factory=lambda: os.getenv("DB_URL", "sqlite:///./data/ragent-v4-flash.db")
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

    def __post_init__(self) -> None:
        # Fail fast only for production-like environments.  Local development
        # intentionally keeps the historical fallback secret for compatibility.
        validate_jwt_secret(self.environment)

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
