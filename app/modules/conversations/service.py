from __future__ import annotations

import json
import uuid
from datetime import datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.framework.errors import AppError
from app.modules.conversations.models import (
    ChatRequestRun,
    Conversation,
    ConversationTurn,
    Message,
)


class ConversationService:
    def create(self, db: Session, user_id: int, title: str = "新对话") -> Conversation:
        item = Conversation(id=str(uuid.uuid4()), user_id=user_id, title=title)
        db.add(item)
        db.commit()
        db.refresh(item)
        return item

    def list(self, db: Session, user_id: int) -> list[Conversation]:
        return list(
            db.scalars(
                select(Conversation)
                .where(Conversation.user_id == user_id)
                .order_by(
                    func.coalesce(Conversation.last_message_at, Conversation.updated_at).desc()
                )
            )
        )

    def require_owned(self, db: Session, conversation_id: str, user_id: int) -> Conversation:
        item = db.get(Conversation, conversation_id)
        if not item or item.user_id != user_id:
            raise AppError("CONVERSATION_NOT_FOUND", "会话不存在", 404)
        return item

    def messages(self, db: Session, conversation_id: str, user_id: int) -> list[Message]:
        self.require_owned(db, conversation_id, user_id)
        return list(
            db.scalars(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at.asc(), Message.id.asc())
            )
        )

    def add_message(
        self,
        db: Session,
        *,
        conversation_id: str,
        user_id: int,
        role: str,
        content: str,
        citations: list[dict] | None = None,
        message_status: str = "NORMAL",
        thinking_content: str | None = None,
        thinking_duration_ms: int | None = None,
        turn_id: int | None = None,
        version: int | None = None,
    ) -> Message:
        conversation = self.require_owned(db, conversation_id, user_id)
        message = Message(
            conversation_id=conversation_id,
            user_id=user_id,
            turn_id=turn_id,
            version=version,
            role=role,
            content=content,
            citations_json=json.dumps(citations, ensure_ascii=False) if citations else None,
            message_status=message_status,
            thinking_content=thinking_content,
            thinking_duration_ms=thinking_duration_ms,
        )
        db.add(message)
        conversation.last_message_at = datetime.utcnow()
        db.commit()
        db.refresh(message)
        return message

    def create_turn(
        self,
        db: Session,
        *,
        conversation_id: str,
        user_id: int,
        question: str,
        rag_enabled: bool,
        deep_thinking: bool,
        knowledge_base_ids: list[int],
    ) -> tuple[ConversationTurn, Message]:
        self.require_owned(db, conversation_id, user_id)
        sequence = (
            db.scalar(
                select(func.max(ConversationTurn.sequence)).where(
                    ConversationTurn.conversation_id == conversation_id
                )
            )
            or 0
        ) + 1
        turn = ConversationTurn(
            conversation_id=conversation_id,
            sequence=sequence,
            status="processing",
            rag_enabled=rag_enabled,
            deep_thinking=deep_thinking,
            knowledge_base_ids_json=json.dumps(
                sorted(set(knowledge_base_ids)), ensure_ascii=False
            ),
        )
        db.add(turn)
        db.commit()
        db.refresh(turn)
        user_message = self.add_message(
            db,
            conversation_id=conversation_id,
            user_id=user_id,
            role="user",
            content=question,
            turn_id=turn.id,
        )
        turn.user_message_id = user_message.id
        db.commit()
        return turn, user_message

    def require_owned_turn(
        self, db: Session, turn_id: int, user_id: int
    ) -> ConversationTurn:
        turn = db.get(ConversationTurn, turn_id)
        if not turn:
            raise AppError("TURN_NOT_FOUND", "对话轮次不存在", 404)
        self.require_owned(db, turn.conversation_id, user_id)
        return turn

    def active_history(
        self,
        db: Session,
        conversation_id: str,
        user_id: int,
        *,
        before_sequence: int | None = None,
    ) -> list[tuple[Message, Message]]:
        self.require_owned(db, conversation_id, user_id)
        statement = (
            select(ConversationTurn)
            .where(
                ConversationTurn.conversation_id == conversation_id,
                ConversationTurn.status == "completed",
                ConversationTurn.user_message_id.is_not(None),
                ConversationTurn.active_assistant_message_id.is_not(None),
            )
            .order_by(ConversationTurn.sequence.asc())
        )
        if before_sequence is not None:
            statement = statement.where(ConversationTurn.sequence < before_sequence)
        turns = list(db.scalars(statement))
        history: list[tuple[Message, Message]] = []
        for turn in turns:
            user_message = db.get(Message, turn.user_message_id)
            assistant_message = db.get(Message, turn.active_assistant_message_id)
            if (
                user_message is not None
                and assistant_message is not None
                # REJECTED/ESCALATED 是「正常完成的受限结果」（拒绝/资料不足的
                # 确定性回答），同样进入历史上下文，供后续轮次回溯
                and assistant_message.message_status
                in ("NORMAL", "REJECTED", "ESCALATED")
            ):
                history.append((user_message, assistant_message))
        if turns:
            return history

        # Legacy conversations have no Turn rows. Preserve only complete user/assistant pairs.
        pending_user: Message | None = None
        for message in self.messages(db, conversation_id, user_id):
            if message.role == "user":
                pending_user = message
            elif (
                message.role == "assistant"
                and message.message_status in ("NORMAL", "REJECTED", "ESCALATED")
                and pending_user is not None
            ):
                history.append((pending_user, message))
                pending_user = None
        return history

    def add_assistant_version(
        self,
        db: Session,
        *,
        turn: ConversationTurn,
        user_id: int,
        content: str,
        citations: list[dict] | None,
        message_status: str,
        thinking_content: str | None = None,
        thinking_duration_ms: int | None = None,
    ) -> Message:
        version = (
            db.scalar(
                select(func.max(Message.version)).where(
                    Message.turn_id == turn.id,
                    Message.role == "assistant",
                )
            )
            or 0
        ) + 1
        message = self.add_message(
            db,
            conversation_id=turn.conversation_id,
            user_id=user_id,
            role="assistant",
            content=content,
            citations=citations,
            message_status=message_status,
            thinking_content=thinking_content,
            thinking_duration_ms=thinking_duration_ms,
            turn_id=turn.id,
            version=version,
        )
        # REJECTED/ESCALATED 是「正常完成的受限结果」（拒绝/资料不足的确定性回答），
        # 同样视为完成态：turn 进入历史，后续轮次可回溯上下文。
        if message_status in ("NORMAL", "REJECTED", "ESCALATED"):
            turn.active_assistant_message_id = message.id
            turn.status = "completed"
        elif turn.active_assistant_message_id is None:
            turn.status = "cancelled" if message_status == "INTERRUPTED" else "failed"
        db.commit()
        return message

    def turn_versions(
        self, db: Session, turn_id: int, user_id: int
    ) -> list[Message]:
        self.require_owned_turn(db, turn_id, user_id)
        return list(
            db.scalars(
                select(Message)
                .where(Message.turn_id == turn_id, Message.role == "assistant")
                .order_by(Message.version.asc(), Message.id.asc())
            )
        )

    def delete(self, db: Session, conversation_id: str, user_id: int) -> None:
        item = self.require_owned(db, conversation_id, user_id)
        turn_ids = select(ConversationTurn.id).where(
            ConversationTurn.conversation_id == conversation_id
        )
        db.execute(
            delete(ChatRequestRun).where(ChatRequestRun.conversation_id == conversation_id)
        )
        db.execute(
            update(Message)
            .where(Message.conversation_id == conversation_id)
            .values(turn_id=None)
        )
        db.execute(
            update(ConversationTurn)
            .where(ConversationTurn.id.in_(turn_ids))
            .values(user_message_id=None, active_assistant_message_id=None)
        )
        db.execute(delete(Message).where(Message.conversation_id == conversation_id))
        db.execute(delete(ConversationTurn).where(ConversationTurn.id.in_(turn_ids)))
        db.delete(item)
        db.commit()

    def rename(
        self, db: Session, conversation_id: str, user_id: int, title: str
    ) -> Conversation:
        item = self.require_owned(db, conversation_id, user_id)
        item.title = title
        db.commit()
        db.refresh(item)
        return item
