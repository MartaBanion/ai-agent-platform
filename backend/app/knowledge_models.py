from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text, false, func, true
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=true())
    shared: Mapped[bool] = mapped_column(Boolean, server_default=false())
    profile: Mapped[str] = mapped_column(String(240))
    dimension: Mapped[int] = mapped_column(Integer)
    chunk_size: Mapped[int] = mapped_column(Integer)
    overlap: Mapped[int] = mapped_column(Integer)
    top_k: Mapped[int] = mapped_column(Integer)
    threshold: Mapped[float] = mapped_column(Float)


class Document(Base):
    __tablename__ = "knowledge_documents"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    knowledge_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    format: Mapped[str] = mapped_column(String(8))
    size: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))
    error: Mapped[str | None] = mapped_column(String(180))
    revision: Mapped[UUID] = mapped_column(default=uuid4)
    data: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Passage(Base):
    __tablename__ = "knowledge_passages"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    page: Mapped[int | None] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)


class AgentKnowledge(Base):
    __tablename__ = "agent_knowledge"
    agent_id: Mapped[UUID] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True)
    knowledge_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_bases.id", ondelete="RESTRICT"), primary_key=True)


class ToolServer(Base):
    __tablename__ = "tool_servers"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(16))
    url: Mapped[str] = mapped_column(String(320))
    key_ciphertext: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=true())
    shared: Mapped[bool] = mapped_column(Boolean, server_default=false())
    approval: Mapped[bool] = mapped_column(Boolean, server_default=true())
    tools: Mapped[dict] = mapped_column(JSONB)
    allowed: Mapped[list] = mapped_column(JSONB)


class AgentTool(Base):
    __tablename__ = "agent_tools"
    agent_id: Mapped[UUID] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True)
    server_id: Mapped[UUID] = mapped_column(ForeignKey("tool_servers.id", ondelete="RESTRICT"), primary_key=True)
    name: Mapped[str] = mapped_column(String(80), primary_key=True)


class ToolCall(Base):
    __tablename__ = "tool_calls"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    server_id: Mapped[UUID | None] = mapped_column(ForeignKey("tool_servers.id", ondelete="SET NULL"), index=True)
    agent_id: Mapped[UUID | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"))
    reviewer_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(80))
    state: Mapped[str] = mapped_column(String(16))
    fingerprint: Mapped[str] = mapped_column(String(64))
    arguments: Mapped[dict | None] = mapped_column(JSONB)
    result: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(String(180))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
