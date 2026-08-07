from __future__ import annotations

import json
import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.framework.errors import AppError
from app.modules.conversations.models import Conversation, Message


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
                .order_by(Conversation.updated_at.desc())
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
    ) -> Message:
        self.require_owned(db, conversation_id, user_id)
        message = Message(
            conversation_id=conversation_id,
            user_id=user_id,
            role=role,
            content=content,
            citations_json=json.dumps(citations, ensure_ascii=False) if citations else None,
        )
        db.add(message)
        db.commit()
        db.refresh(message)
        return message

    def delete(self, db: Session, conversation_id: str, user_id: int) -> None:
        item = self.require_owned(db, conversation_id, user_id)
        db.execute(delete(Message).where(Message.conversation_id == conversation_id))
        db.delete(item)
        db.commit()
