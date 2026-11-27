import logging
import os
from datetime import UTC, datetime, timedelta
from threading import BoundedSemaphore
from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Cookie, Depends, HTTPException, Response
from pwdlib import PasswordHash
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import LoginSession, User

COOKIE = "platform_session"
ISSUER = "ai-agent-platform"
TTL = timedelta(minutes=30)
JWT_SECRET = os.environ["PLATFORM_JWT_SECRET"]
if len(JWT_SECRET) < 32:
    raise RuntimeError("PLATFORM_JWT_SECRET must contain at least 32 characters")
COOKIE_SECURE = os.environ.get("PLATFORM_COOKIE_SECURE", "false").lower() == "true"
password_hash = PasswordHash.recommended()
hash_slots = BoundedSemaphore(2)
Db = Annotated[Session, Depends(get_db)]


def hash_password(password: str) -> str:
    with hash_slots:
        return password_hash.hash(password)


dummy_hash = hash_password("invalid-login-dummy-password")


def verify_password(password: str, stored_hash: str) -> bool:
    with hash_slots:
        return password_hash.verify(password, stored_hash)


def require_session(db: Db, token: Annotated[str | None, Cookie(alias=COOKIE)] = None):
    unauthorized = HTTPException(401, "请先登录")
    try:
        claims = jwt.decode(token or "", JWT_SECRET, algorithms=["HS256"], issuer=ISSUER,
                            options={"require": ["sub", "jti", "exp", "iat", "iss"]})
        user_id, session_id = UUID(claims["sub"]), UUID(claims["jti"])
    except (jwt.InvalidTokenError, TypeError, ValueError):
        raise unauthorized from None

    result = db.execute(
        select(User, LoginSession)
        .join(LoginSession, LoginSession.user_id == User.id)
        .where(User.id == user_id, User.is_active.is_(True),
               LoginSession.id == session_id, LoginSession.expires_at > datetime.now(UTC))
    ).one_or_none()
    if result is None:
        raise unauthorized
    return result.User, result.LoginSession


Identity = Annotated[tuple[User, LoginSession], Depends(require_session)]


def require_admin(identity: Identity) -> User:
    user, _ = identity
    if user.role != "admin":
        raise HTTPException(403, "需要管理员权限")
    return user


Admin = Annotated[User, Depends(require_admin)]


def issue_session(db: Session, response: Response, user: User):
    now = datetime.now(UTC)
    session = LoginSession(user_id=user.id, expires_at=now + TTL)
    db.execute(delete(LoginSession).where(LoginSession.expires_at <= now))
    db.add(session)
    db.flush()
    token = jwt.encode({"sub": str(user.id), "jti": str(session.id), "iss": ISSUER,
                        "iat": now, "exp": session.expires_at}, JWT_SECRET, algorithm="HS256")
    db.commit()
    response.set_cookie(COOKIE, token, max_age=int(TTL.total_seconds()), path="/api/v1",
                        httponly=True, secure=COOKIE_SECURE, samesite="strict")


def clear_session_cookie(response: Response):
    response.delete_cookie(COOKIE, path="/api/v1", httponly=True,
                           secure=COOKIE_SECURE, samesite="strict")


def audit(event: str, actor: UUID, target: UUID | None = None):
    logging.getLogger("platform").info(event, extra={"actor_id": str(actor), "target_id": str(target or actor)})
