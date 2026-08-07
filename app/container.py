from __future__ import annotations

from dataclasses import dataclass

from app.framework.config import Settings
from app.infra_ai.circuit_breaker import CircuitBreaker
from app.infra_ai.providers.openai_compatible import OpenAICompatibleChatModel
from app.infra_ai.router import ChatModelRouter, RoutedProvider


@dataclass(slots=True)
class ApplicationContainer:
    settings: Settings
    chat_router: ChatModelRouter | None


def build_container(settings: Settings) -> ApplicationContainer:
    providers: list[RoutedProvider] = []
    for endpoint in settings.chat_endpoints():
        providers.append(
            RoutedProvider(
                model=OpenAICompatibleChatModel(
                    name=endpoint.name,
                    base_url=endpoint.base_url,
                    api_key=endpoint.api_key,
                    model=endpoint.model,
                    reasoning_model=endpoint.reasoning_model,
                ),
                breaker=CircuitBreaker(
                    failure_threshold=settings.circuit_failure_threshold,
                    recovery_seconds=settings.circuit_recovery_seconds,
                ),
                priority=endpoint.priority,
            )
        )
    chat_router = (
        ChatModelRouter(
            providers,
            timeout_seconds=settings.chat_timeout_seconds,
            first_token_timeout_seconds=settings.chat_first_token_timeout_seconds,
            idle_timeout_seconds=settings.chat_idle_timeout_seconds,
        )
        if providers
        else None
    )
    return ApplicationContainer(settings=settings, chat_router=chat_router)
