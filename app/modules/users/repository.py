from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.users.models import User


class UserRepository:
    def get_by_username(self, db: Session, username: str) -> User | None:
        return db.scalar(select(User).where(User.username == username))

    def get(self, db: Session, user_id: int) -> User | None:
        return db.get(User, user_id)

    def create(
        self, db: Session, *, username: str, password_hash: str, email: str | None = None
    ) -> User:
        user = User(username=username, password_hash=password_hash, email=email)
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
