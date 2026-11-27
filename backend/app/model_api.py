from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import Field, SecretStr, StringConstraints
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError

from app.ai_models import Agent, Execution, ModelConfig
from app.execution import begin, probe_response, serialize
from app.provider import UpstreamError, canonical_url, encrypt_key, model_events
from app.schemas import Input, Name
from app.security import Admin, Db, Identity, audit

router = APIRouter(prefix="/models", tags=["模型中心"])


class ModelForm(Input):
    name: Name
    provider: Literal["openai", "deepseek", "qwen", "custom"]
    base_url: str = Field("", max_length=320)
    model: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
    api_key: SecretStr | None = Field(None, max_length=1024)
    clear_key: bool = False
    temperature: float = Field(0.3, ge=0, le=2)
    max_tokens: int = Field(1024, ge=1, le=8192)
    timeout: int = Field(45, ge=5, le=90)
    enabled: bool = True
    is_default: bool = False


def model_config(model):
    return {name: getattr(model, name) for name in (
        "provider", "base_url", "model", "key_ciphertext", "temperature", "max_tokens", "timeout"
    )}


def choice(model):
    return {name: getattr(model, name) for name in ("id", "name", "model", "provider", "is_default")}


def model_view(model):
    return {**choice(model), "base_url": model.base_url, "enabled": model.enabled,
            "temperature": model.temperature, "max_tokens": model.max_tokens, "timeout": model.timeout,
            "has_key": bool(model.key_ciphertext)}


def selected(db, key, default=True):
    model = db.get(ModelConfig, key) if key else None
    if key is None and default:
        model = db.scalar(select(ModelConfig).where(ModelConfig.enabled, ModelConfig.is_default))
    if not model or not model.enabled:
        raise HTTPException(409, "请选择已启用的模型")
    return model


def get_model(db, key):
    model = db.get(ModelConfig, key)
    if not model:
        raise HTTPException(404, "模型不存在")
    return model


@router.get("/options")
def options(db: Db, identity: Identity):
    return [choice(model) for model in db.scalars(select(ModelConfig).where(ModelConfig.enabled)
                                                  .order_by(ModelConfig.is_default.desc(), ModelConfig.name))]


@router.get("")
def list_models(db: Db, admin: Admin):
    return [model_view(model) for model in db.scalars(select(ModelConfig).order_by(ModelConfig.name))]


def save(db, model, form, admin):
    try:
        base_url = canonical_url(form.provider, form.base_url)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    if form.is_default and not form.enabled:
        raise HTTPException(422, "默认模型必须启用")
    secret = form.api_key.get_secret_value() if form.api_key is not None else None
    if secret and (not secret.isascii() or not all(33 <= ord(char) <= 126 for char in secret)):
        raise HTTPException(422, "API Key 格式无效")
    if not secret and model.key_ciphertext and not form.clear_key and model.base_url != base_url:
        raise HTTPException(422, "切换地址时须重新填写或清除 API Key")
    try:
        if secret:
            model.key_ciphertext = encrypt_key(secret)
        elif form.clear_key:
            model.key_ciphertext = None
    except UpstreamError as error:
        raise HTTPException(503, str(error)) from None
    for field, value in form.model_dump(exclude={"api_key", "clear_key", "base_url"}).items():
        setattr(model, field, value)
    model.base_url = base_url
    if form.is_default:
        with db.no_autoflush:
            db.execute(update(ModelConfig).where(ModelConfig.is_default).values(is_default=False),
                       execution_options={"synchronize_session": False})
        # Force the selected row's default back to true even when it was already true.
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(model, "is_default")
    db.add(model)
    try:
        db.commit()
    except IntegrityError:
        raise HTTPException(409, "模型名称已存在或默认模型冲突") from None
    audit("model_saved", admin.id, model.id)
    return model_view(model)


def lock_models(db):
    db.execute(text("SELECT pg_advisory_xact_lock(400282)"))


@router.post("", status_code=201)
def create(form: ModelForm, db: Db, admin: Admin):
    lock_models(db)
    return save(db, ModelConfig(), form, admin)


@router.put("/{key}")
def change(key: UUID, form: ModelForm, db: Db, admin: Admin):
    lock_models(db)
    return save(db, get_model(db, key), form, admin)


@router.delete("/{key}", status_code=204)
def remove(key: UUID, db: Db, admin: Admin):
    lock_models(db)
    model = get_model(db, key)
    if db.scalar(select(Agent.id).where(Agent.model_id == key).limit(1)):
        raise HTTPException(409, "请先解除智能体的模型关联")
    db.delete(model)
    try:
        db.commit()
    except IntegrityError:
        raise HTTPException(409, "模型仍被引用") from None
    audit("model_deleted", admin.id, key)


@router.get("/{key}/usage")
def summary(key: UUID, db: Db, admin: Admin):
    get_model(db, key)
    row = db.execute(select(
        func.count(Execution.id).label("calls"),
        func.count(Execution.id).filter(Execution.status == "success").label("success"),
        func.avg(Execution.duration_ms).label("avg_ms"),
        func.sum(Execution.input_tokens).label("input_tokens"),
        func.sum(Execution.output_tokens).label("output_tokens"),
        func.sum(Execution.total_tokens).label("total_tokens"),
    ).where(Execution.model_id == key)).mappings().one()
    return dict(row)


@router.post("/{key}/test")
async def probe(key: UUID, db: Db, admin: Admin):
    model = get_model(db, key)
    config = model_config(model)
    execution = begin(db, admin, "model_test", model=model.id)
    execution_id = execution.id
    db.commit()
    events = model_events(config, [{"role": "user", "content": "Reply briefly with OK."}], stream=False)
    return await probe_response(events, execution_id)


@router.get("/{key}/history")
def history(key: UUID, db: Db, admin: Admin):
    get_model(db, key)
    rows = db.scalars(select(Execution).where(Execution.model_id == key)
                      .order_by(Execution.created_at.desc()).limit(50))
    return [serialize(row) for row in rows]
