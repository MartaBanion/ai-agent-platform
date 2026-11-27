from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import Field, model_validator
from sqlalchemy import select

from app.agent_api import agent_runtime
from app.ai_access import owned
from app.ai_models import Conversation, Execution, Message
from app.execution import begin, stream_response
from app.flow_runtime import flow_events
from app.model_api import model_config, selected
from app.provider import model_events
from app.schemas import Input, Name
from app.security import Db, Identity

router = APIRouter(prefix="/conversations", tags=["对话"])


class Title(Input):
    title: Name = "新对话"


class Send(Input):
    text: str = Field("", max_length=12000)
    retry: bool = False
    model_id: UUID | None = None
    agent_id: UUID | None = None

    @model_validator(mode="after")
    def validate_send(self):
        if self.model_id and self.agent_id:
            raise ValueError("模型与智能体只能选择一个")
        if not self.retry and not self.text.strip():
            raise ValueError("消息不可为空")
        return self


def view(row):
    return {"id": row.id, "title": row.title, "updated_at": row.updated_at}


def get(db, key, user, locked=False):
    return owned(db.get(Conversation, key, with_for_update=locked), user, allow_admin=False)


@router.get("")
def list_conversations(db: Db, identity: Identity):
    statement = (select(Conversation).where(Conversation.owner_id == identity[0].id)
                 .order_by(Conversation.updated_at.desc()).limit(200))
    return [view(row) for row in db.scalars(statement)]


@router.post("", status_code=201)
def add(payload: Title, db: Db, identity: Identity):
    row = Conversation(owner_id=identity[0].id, title=payload.title)
    db.add(row)
    db.commit()
    return view(row)


@router.patch("/{key}")
def rename(key: UUID, payload: Title, db: Db, identity: Identity):
    row = get(db, key, identity[0], locked=True)
    row.title = payload.title
    row.updated_at = datetime.now(UTC)
    db.commit()
    return view(row)


@router.delete("/{key}", status_code=204)
def remove(key: UUID, db: Db, identity: Identity):
    row = get(db, key, identity[0], locked=True)
    if db.scalar(select(Execution.id).where(Execution.conversation_id == key, Execution.status == "running")):
        raise HTTPException(409, "请先停止会话生成")
    db.delete(row)
    db.commit()


@router.get("/{key}/messages")
def messages(key: UUID, db: Db, identity: Identity):
    get(db, key, identity[0])
    statement = (select(Message).where(Message.conversation_id == key)
                 .order_by(Message.created_at.desc(), Message.id.desc()).limit(200))
    return [{"id": row.id, "role": row.role, "content": row.content, "created_at": row.created_at}
            for row in reversed(list(db.scalars(statement)))]


def context(db, key, limit):
    rows = db.scalars(select(Message).where(Message.conversation_id == key)
                      .order_by(Message.created_at.desc(), Message.id.desc()).limit(24))
    stack = []
    for row in rows:
        if len(row.content) > limit and stack:
            break
        stack.append({"role": row.role, "content": row.content[-limit:]})
        limit -= len(stack[-1]["content"])
        if limit <= 0:
            break
    return list(reversed(stack))


@router.post("/{key}/generate")
def generate(key: UUID, payload: Send, db: Db, identity: Identity):
    user = identity[0]
    row = get(db, key, user, locked=True)
    agent = workflow = None
    if payload.agent_id:
        agent, workflow, model = agent_runtime(db, user, payload.agent_id)
    else:
        model = selected(db, payload.model_id)
    execution = begin(db, user, "agent" if agent else "chat", conversation=key,
                      model=model.id if model else None, agent=agent.id if agent else None,
                      workflow=workflow.id if workflow else None)
    history = context(db, key, 36000)
    if payload.retry:
        if not history or history[-1]["role"] != "user":
            raise HTTPException(409, "没有可重试的消息")
    else:
        text = payload.text.strip()
        if not history and row.title == "新对话":
            row.title = text.splitlines()[0][:60]
        db.add(Message(conversation_id=key, role="user", content=text))
        history.append({"role": "user", "content": text})
    row.updated_at = datetime.now(UTC)
    config = model_config(model) if model else None
    if agent:
        text = history[-1]["content"]
        if workflow.kind == "prompt" and len(history) > 1:
            prior = "\n".join(("用户" if item["role"] == "user" else "助手") + "：" + item["content"]
                              for item in history[:-1])
            text = f"对话历史：\n{prior}\n\n用户当前消息：\n{text}"
        events = flow_events(workflow.engine_id, workflow.kind, workflow.digest, text, key,
                             config, agent.system_prompt)
    else:
        events = model_events(config, history)
    execution_id = execution.id
    db.commit()
    return stream_response(events, execution_id)
