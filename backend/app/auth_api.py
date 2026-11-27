from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import delete, select

from app.models import LoginSession, User
from app.schemas import ChangePassword, Login, UserView
from app.security import (Db, Identity, audit, clear_session_cookie, dummy_hash, hash_password,
                          issue_session, verify_password)

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post("/login", response_model=UserView)
def login(payload: Login, response: Response, db: Db):
    user = db.scalar(select(User).where(User.username == payload.username).with_for_update())
    matches = verify_password(payload.password, user.password_hash if user else dummy_hash)
    if not matches or not user or not user.is_active:
        raise HTTPException(401, "用户名或密码错误")
    issue_session(db, response, user)
    audit("login", user.id)
    return user


@router.get("/me", response_model=UserView)
def profile(identity: Identity):
    return identity[0]


@router.post("/logout", status_code=204)
def logout(response: Response, db: Db, identity: Identity):
    user, session = identity
    db.execute(delete(LoginSession).where(LoginSession.id == session.id))
    db.commit()
    clear_session_cookie(response)
    audit("logout", user.id)


@router.post("/password", status_code=204)
def change_password(payload: ChangePassword, response: Response, db: Db, identity: Identity):
    user = db.scalar(select(User).where(User.id == identity[0].id).with_for_update()
                     .execution_options(populate_existing=True))
    if not user or not user.is_active or not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(400, "当前密码不正确")
    user.password_hash = hash_password(payload.new_password)
    db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
    db.commit()
    clear_session_cookie(response)
    audit("password_changed", user.id)
