from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException
from pydantic import Field
from sqlalchemy import or_, select

from app.ai_access import owned, require_builder, shared_agent
from app.agent_resources import checked_tool_context
from app.knowledge_api import agent_references, rag_context
from app.ai_models import Agent, Execution, Workflow
from app.execution import begin, serialize, stream_response
from app.flow_runtime import MODEL_PROVIDERS, flow_events
from app.model_api import model_config, selected
from app.schemas import Input, Name
from app.security import Db, Identity, audit

router = APIRouter(prefix="/agents", tags=["智能体"])


class AgentForm(Input):
    name: Name
    description: str = Field("", max_length=1000)
    icon: str = Field("🤖", max_length=16)
    system_prompt: str = Field("", max_length=6000)
    model_id: UUID | None = None
    workflow_id: UUID
    enabled: bool = True
    published: bool = False


class AgentRun(Input):
    text: str = Field(min_length=1, max_length=12000)
    tool_call_id: UUID | None = None


def view(agent, user):
    editable = user.role == "admin" or agent.owner_id == user.id
    info = {key: getattr(agent, key) for key in ("id", "name", "description", "icon", "enabled", "published")}
    info["editable"] = editable
    if editable:
        info.update({key: getattr(agent, key) for key in ("system_prompt", "model_id", "workflow_id")})
    return info


@router.get("")
def list_agents(db: Db, identity: Identity):
    user = identity[0]
    statement = select(Agent).order_by(Agent.name)
    if user.role != "admin":
        statement = statement.where(or_(Agent.owner_id == user.id, Agent.enabled & Agent.published))
    return [view(agent, user) for agent in db.scalars(statement)]


@router.get("/{key}")
def detail(key: UUID, db: Db, identity: Identity):
    return view(shared_agent(db.get(Agent, key), identity[0]), identity[0])


def save(db, user, agent, payload):
    workflow = owned(db.get(Workflow, payload.workflow_id), user)
    if payload.model_id:
        model = selected(db, payload.model_id)
        if workflow.kind == "prompt" and model.provider not in MODEL_PROVIDERS:
            raise HTTPException(422, "此工作流模板只支持 OpenAI 和 DeepSeek")
    if payload.published and not payload.enabled:
        raise HTTPException(422, "请启用智能体后再发布")
    for key, value in payload.model_dump().items():
        setattr(agent, key, value)
    db.add(agent)
    db.commit()
    audit("agent_saved", user.id, agent.id)
    return view(agent, user)


@router.post("", status_code=201)
def add(payload: AgentForm, db: Db, identity: Identity):
    user = identity[0]
    require_builder(user)
    return save(db, user, Agent(owner_id=user.id), payload)


@router.put("/{key}")
def update(key: UUID, payload: AgentForm, db: Db, identity: Identity):
    user = identity[0]
    require_builder(user)
    return save(db, user, owned(db.get(Agent, key), user), payload)


@router.delete("/{key}", status_code=204)
def remove(key: UUID, db: Db, identity: Identity):
    user = identity[0]
    require_builder(user)
    db.delete(owned(db.get(Agent, key), user))
    db.commit()
    audit("agent_deleted", user.id, key)


def agent_runtime(db, user, key):
    agent = shared_agent(db.get(Agent, key), user)
    if not agent.enabled:
        raise HTTPException(409, "智能体已停用")
    workflow = db.get(Workflow, agent.workflow_id)
    model = selected(db, agent.model_id) if workflow.kind == "prompt" else None
    return agent, workflow, model


@router.post("/{key}/run")
def run(key: UUID, payload: AgentRun, db: Db, identity: Identity):
    user = identity[0]
    agent, workflow, model = agent_runtime(db, user, key)
    references, prompt = [], payload.text
    if workflow.kind == "prompt":
        references = agent_references(db, key, user, payload.text)
        prompt = rag_context(payload.text, references) + checked_tool_context(db, agent, user, payload.tool_call_id)
    elif payload.tool_call_id:
        raise HTTPException(422, "文本直通流程不能合并工具上下文")
    execution = begin(db, user, "agent", agent=key, workflow=workflow.id, model=model.id if model else None)
    events = flow_events(workflow.engine_id, workflow.kind, workflow.digest, prompt, uuid4(),
                         model_config(model) if model else None, agent.system_prompt)
    execution_id = execution.id
    db.commit()
    return stream_response(events, execution_id, references)


@router.get("/{key}/history")
def history(key: UUID, db: Db, identity: Identity):
    user = identity[0]
    shared_agent(db.get(Agent, key), user)
    statement = select(Execution).where(Execution.agent_id == key).order_by(Execution.created_at.desc()).limit(50)
    if user.role != "admin":
        statement = statement.where(Execution.owner_id == user.id)
    return [serialize(row) for row in db.scalars(statement)]
