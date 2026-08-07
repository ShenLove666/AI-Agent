from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.framework.errors import AppError
from app.modules.users.models import User
from app.modules.users.repository import UserRepository
from app.modules.users.schemas import LoginRequest, RegisterRequest, TokenResponse


class AuthService:
    algorithm = "HS256"

    def __init__(self, repository: UserRepository):
        self.repository = repository
        self.secret = os.getenv("JWT_SECRET", "change-me-before-production")
        self.expire_minutes = int(os.getenv("JWT_EXPIRE_MINUTES", "43200"))
        self.passwords = CryptContext(schemes=["argon2"], deprecated="auto")

    def register(self, db: Session, request: RegisterRequest) -> User:
        if self.repository.get_by_username(db, request.username):
            raise AppError("USERNAME_EXISTS", "用户名已存在", 409)
        return self.repository.create(
            db,
            username=request.username,
            password_hash=self.passwords.hash(request.password),
            email=request.email,
        )

    def login(self, db: Session, request: LoginRequest) -> TokenResponse:
        user = self.repository.get_by_username(db, request.username)
        if not user or not self.passwords.verify(request.password, user.password_hash):
            raise AppError("INVALID_CREDENTIALS", "用户名或密码错误", 401)
        if not user.is_active:
            raise AppError("USER_DISABLED", "用户已被停用", 403)
        token = jwt.encode(
            {
                "sub": str(user.id),
                "username": user.username,
                "role": user.role,
                "exp": datetime.now(timezone.utc) + timedelta(minutes=self.expire_minutes),
            },
            self.secret,
            algorithm=self.algorithm,
        )
        return TokenResponse(
            access_token=token, user_id=user.id, username=user.username, role=user.role
        )

    def decode_user_id(self, token: str) -> int:
        try:
            payload = jwt.decode(token, self.secret, algorithms=[self.algorithm])
            return int(payload["sub"])
        except (JWTError, KeyError, TypeError, ValueError) as exc:
            raise AppError("INVALID_TOKEN", "认证失效，请重新登录", 401) from exc
