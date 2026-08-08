from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.framework.errors import AppError
from app.modules.orders.models import OutboundMessage
from app.modules.support.models import ReplySuggestion, SupportCase, SupportEvent, SupportMessage


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    channel: str
    status: str
    external_id: str | None
    is_demo: bool
    failure_reason: str | None = None


class CustomerChannel(Protocol):
    def send(self, *, content: str, idempotency_key: str) -> DeliveryResult: ...


class DemoChannel:
    """A local adapter that simulates dispatch and never claims customer delivery."""

    def send(self, *, content: str, idempotency_key: str) -> DeliveryResult:
        return DeliveryResult(
            channel="demo",
            status="sent",
            external_id=f"demo:{idempotency_key}",
            is_demo=True,
        )


class WebhookChannel:
    """One-attempt signed delivery adapter with deliberately bounded behavior."""

    def __init__(
        self,
        url: str,
        secret: str,
        *,
        client: httpx.Client | None = None,
        timeout_seconds: float = 5.0,
        max_payload_bytes: int = 32_768,
    ):
        self._url = url
        self._secret = secret.encode()
        self._client = client or httpx.Client()
        self._timeout_seconds = max(0.1, min(timeout_seconds, 30.0))
        self._max_payload_bytes = max(1024, max_payload_bytes)

    def send(self, *, content: str, idempotency_key: str) -> DeliveryResult:
        body = json.dumps(
            {"content": content, "idempotencyKey": idempotency_key},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(body) > self._max_payload_bytes:
            return DeliveryResult(
                channel="webhook",
                status="failed",
                external_id=None,
                is_demo=False,
                failure_reason="WEBHOOK_PAYLOAD_TOO_LARGE",
            )
        signature = hmac.new(self._secret, body, hashlib.sha256).hexdigest()
        try:
            response = self._client.post(
                self._url,
                content=body,
                headers={
                    "content-type": "application/json",
                    "x-ragent-signature": f"sha256={signature}",
                    "idempotency-key": idempotency_key,
                },
                timeout=self._timeout_seconds,
            )
        except httpx.TimeoutException:
            return DeliveryResult(
                channel="webhook",
                status="failed",
                external_id=None,
                is_demo=False,
                failure_reason="WEBHOOK_TIMEOUT",
            )
        except httpx.RequestError:
            return DeliveryResult(
                channel="webhook",
                status="failed",
                external_id=None,
                is_demo=False,
                failure_reason="WEBHOOK_REQUEST_FAILED",
            )
        if not 200 <= response.status_code < 300:
            return DeliveryResult(
                channel="webhook",
                status="failed",
                external_id=None,
                is_demo=False,
                failure_reason=f"WEBHOOK_HTTP_{response.status_code}",
            )
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        status = payload.get("status") if isinstance(payload, dict) else None
        if status not in {"queued", "sent", "delivered"}:
            status = "sent"
        external_id = payload.get("externalId") if isinstance(payload, dict) else None
        return DeliveryResult(
            channel="webhook",
            status=status,
            external_id=str(external_id) if external_id is not None else None,
            is_demo=False,
        )


class OutboundService:
    def __init__(self, channel: CustomerChannel | None = None):
        self.channel = channel or DemoChannel()

    def confirm(
        self,
        db: Session,
        *,
        owner_id: int,
        case_id: int,
        actor_id: int,
        content: str,
        expected_version: int,
        idempotency_key: str,
        suggestion_id: int | None = None,
    ) -> dict:
        case = db.scalar(
            select(SupportCase).where(
                SupportCase.id == case_id,
                SupportCase.owner_id == owner_id,
            )
        )
        if case is None:
            raise AppError("SUPPORT_CASE_NOT_FOUND", "客服工单不存在", 404)

        existing = db.scalar(
            select(OutboundMessage).where(
                OutboundMessage.owner_id == owner_id,
                OutboundMessage.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            if existing.case_id != case.id or existing.content != content.strip():
                raise AppError(
                    "IDEMPOTENCY_KEY_REUSED",
                    "幂等键已用于不同的外发内容",
                    409,
                )
            return self.serialize(existing)

        clean_content = content.strip()
        if not clean_content:
            raise AppError("EMPTY_REPLY", "回复内容不能为空", 422)
        if case.version != expected_version:
            raise AppError(
                "CASE_VERSION_CONFLICT",
                "工单已被其他成员更新，请刷新后重试",
                409,
            )
        if suggestion_id is not None:
            suggestion = db.scalar(
                select(ReplySuggestion).where(
                    ReplySuggestion.id == suggestion_id,
                    ReplySuggestion.case_id == case.id,
                )
            )
            if suggestion is None:
                raise AppError("SUGGESTION_NOT_FOUND", "回复建议不存在", 404)

        delivery = self.channel.send(
            content=clean_content,
            idempotency_key=idempotency_key,
        )
        now = datetime.utcnow()
        message = SupportMessage(
            case_id=case.id,
            actor_id=actor_id,
            role="agent",
            content=clean_content,
            suggestion_id=suggestion_id,
            sent_to_customer=delivery.status in {"sent", "delivered"},
            created_at=now,
        )
        db.add(message)
        db.flush()
        outbound = OutboundMessage(
            owner_id=owner_id,
            case_id=case.id,
            support_message_id=message.id,
            suggestion_id=suggestion_id,
            idempotency_key=idempotency_key,
            channel=delivery.channel,
            status=delivery.status,
            content=clean_content,
            external_id=delivery.external_id,
            failure_reason=delivery.failure_reason,
            is_demo=delivery.is_demo,
            created_at=now,
            sent_at=now if delivery.status in {"sent", "delivered"} else None,
            delivered_at=now if delivery.status == "delivered" else None,
        )
        db.add(outbound)
        case.unread = False
        case.version += 1
        case.updated_at = now
        db.add(
            SupportEvent(
                owner_id=owner_id,
                case_id=case.id,
                actor_id=actor_id,
                event_type="outbound_confirmed",
                payload_json=(
                    '{"channel":"demo","deliveryClaim":"simulated"}'
                    if delivery.is_demo
                    else '{"deliveryClaim":"external-status"}'
                ),
                is_demo=case.is_demo or delivery.is_demo,
                occurred_at=now,
            )
        )
        db.commit()
        return self.serialize(outbound)

    @staticmethod
    def serialize(item: OutboundMessage) -> dict:
        return {
            "id": item.id,
            "caseId": item.case_id,
            "supportMessageId": item.support_message_id,
            "suggestionId": item.suggestion_id,
            "channel": item.channel,
            "status": item.status,
            "externalId": item.external_id,
            "failureReason": item.failure_reason,
            "isDemo": item.is_demo,
            "deliveryClaim": "simulated" if item.is_demo else "external-status",
            "createdAt": item.created_at.isoformat(),
            "sentAt": item.sent_at.isoformat() if item.sent_at else None,
            "deliveredAt": item.delivered_at.isoformat() if item.delivered_at else None,
        }


def build_customer_channel() -> CustomerChannel:
    mode = os.getenv("CUSTOMER_CHANNEL", "demo").strip().lower()
    if mode == "demo":
        return DemoChannel()
    if mode == "webhook":
        url = os.getenv("CUSTOMER_WEBHOOK_URL", "").strip()
        secret = os.getenv("CUSTOMER_WEBHOOK_SECRET", "")
        if not url or not secret:
            raise RuntimeError(
                "CUSTOMER_CHANNEL=webhook requires CUSTOMER_WEBHOOK_URL and CUSTOMER_WEBHOOK_SECRET"
            )
        return WebhookChannel(
            url,
            secret,
            timeout_seconds=float(os.getenv("CUSTOMER_WEBHOOK_TIMEOUT_SECONDS", "5")),
        )
    raise RuntimeError(f"Unsupported CUSTOMER_CHANNEL: {mode}")
