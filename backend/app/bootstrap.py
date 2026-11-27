import os

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db import engine
from app.ai_models import Execution
from app.models import User
from app.schemas import CreateUser
from app.security import hash_password


def bootstrap():
    with Session(engine) as db:
        db.execute(update(Execution).where(Execution.status == "running")
                   .values(status="cancelled", error="服务重启中断执行"))
        db.commit()
        if db.scalar(select(User.id).where(User.role == "admin", User.is_active.is_(True)).limit(1)):
            return
        admin = CreateUser(username=os.environ.get("PLATFORM_ADMIN_USERNAME", "portal_admin"),
                           display_name="平台管理员", role="admin",
                           password=os.environ["PLATFORM_ADMIN_PASSWORD"])
        inserted = db.scalar(
            insert(User).values(username=admin.username, display_name=admin.display_name,
                                password_hash=hash_password(admin.password), role=admin.role)
            .on_conflict_do_nothing(index_elements=[User.username]).returning(User.id)
        )
        if inserted is None:
            exists = db.scalar(select(User.id).where(User.role == "admin", User.is_active.is_(True)).limit(1))
            if not exists:
                raise RuntimeError("Bootstrap administrator username is already in use")
        db.commit()


if __name__ == "__main__":
    bootstrap()
