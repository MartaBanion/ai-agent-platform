from fastapi import HTTPException


def require_builder(user):
    if user.role not in {"admin", "developer"}:
        raise HTTPException(403, "需要开发者或管理员权限")


def owned(item, user, allow_admin=True):
    if item is None or (item.owner_id != user.id and not (allow_admin and user.role == "admin")):
        raise HTTPException(404, "资源不存在")
    return item


def shared_agent(item, user):
    if item and item.enabled and item.published:
        return item
    return owned(item, user)
