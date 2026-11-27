from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError

from app.models import LoginSession, User
from app.schemas import CreateUser, UpdateUser, UserPage, UserView
from app.security import Admin, Db, audit, hash_password

router = APIRouter(prefix="/users", tags=["用户管理"])


def lock_administration(db: Db, admin: Admin):
    db.execute(text("SELECT pg_advisory_xact_lock(400281)"))
    current = db.scalar(select(User).where(User.id == admin.id).with_for_update()
                        .execution_options(populate_existing=True))
    if not current or not current.is_active or current.role != "admin":
        raise HTTPException(403, "需要管理员权限")


@router.get("", response_model=UserPage)
def list_users(db: Db, admin: Admin, offset: int = Query(0, ge=0),
               limit: int = Query(20, ge=1, le=100)):
    items = db.scalars(select(User).order_by(User.created_at, User.id).offset(offset).limit(limit)).all()
    return {"items": items, "total": db.scalar(select(func.count()).select_from(User))}


@router.post("", response_model=UserView, status_code=201)
def create_user(payload: CreateUser, db: Db, admin: Admin):
    lock_administration(db, admin)
    user = User(**payload.model_dump(exclude={"password"}), password_hash=hash_password(payload.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "用户名已存在") from None
    audit("user_created", admin.id, user.id)
    return user


@router.put("/{user_id}", response_model=UserView)
def update_user(user_id: UUID, payload: UpdateUser, db: Db, admin: Admin):
    lock_administration(db, admin)
    if user_id == admin.id:
        raise HTTPException(409, "请通过个人设置修改自己的密码")
    user = db.get(User, user_id, with_for_update=True)
    if not user:
        raise HTTPException(404, "用户不存在")
    revoke = user.role != payload.role or user.is_active != payload.is_active or payload.password is not None
    user.display_name = payload.display_name
    user.role = payload.role
    user.is_active = payload.is_active
    if payload.password is not None:
        user.password_hash = hash_password(payload.password)
    if revoke:
        db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
    db.commit()
    audit("user_updated", admin.id, user.id)
    return user
