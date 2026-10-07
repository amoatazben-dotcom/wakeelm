"""Durable stage 7/8 state; Redis contains only locks and disposable counters."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, now


class MemoryItem(TimestampMixin, Base):
    __tablename__ = "memory_items"
    __table_args__ = (UniqueConstraint("user_id", "scope_key", "digest"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_jobs.id", ondelete="CASCADE"), index=True
    )
    layer: Mapped[str] = mapped_column(String(30))
    scope_key: Mapped[str] = mapped_column(String(100))
    digest: Mapped[str] = mapped_column(String(64))
    content_encrypted: Mapped[str] = mapped_column(Text)
    search_terms: Mapped[list] = mapped_column(JSON, default=list)
    provenance_json: Mapped[dict] = mapped_column(JSON)
    confidence: Mapped[float] = mapped_column(Numeric(4, 3))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentGraphNode(TimestampMixin, Base):
    __tablename__ = "agent_graph_nodes"
    __table_args__ = (UniqueConstraint("job_id", "node_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("agent_jobs.id", ondelete="CASCADE"), index=True)
    node_key: Mapped[str] = mapped_column(String(80))
    role: Mapped[str] = mapped_column(String(40))
    dependencies: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(30), default="PENDING")
    result_encrypted: Mapped[str | None] = mapped_column(Text)
    model_id: Mapped[int | None] = mapped_column(ForeignKey("models.id", ondelete="SET NULL"))


class UsageEntry(Base):
    __tablename__ = "usage_entries"
    id: Mapped[int] = mapped_column(primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider_id: Mapped[int | None] = mapped_column(
        ForeignKey("providers.id", ondelete="SET NULL"), index=True
    )
    model_id: Mapped[int | None] = mapped_column(ForeignKey("models.id", ondelete="SET NULL"))
    job_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_jobs.id", ondelete="SET NULL"), index=True
    )
    operation: Mapped[str] = mapped_column(String(40), index=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    actual_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    tool_calls: Mapped[int] = mapped_column(Integer, default=0)
    storage_bytes: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(30), default="RESERVED")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class PlanPolicy(TimestampMixin, Base):
    __tablename__ = "plan_policies"
    name: Mapped[str] = mapped_column(String(30), primary_key=True)
    limits_json: Mapped[dict] = mapped_column(JSON)


class UserPlan(TimestampMixin, Base):
    __tablename__ = "user_plans"
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    plan: Mapped[str] = mapped_column(String(30), default="FREE")
    overrides_json: Mapped[dict] = mapped_column(JSON, default=dict)


class FeatureFlag(TimestampMixin, Base):
    __tablename__ = "feature_flags"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean)
    targets_json: Mapped[dict] = mapped_column(JSON, default=dict)


class AdminIdentity(TimestampMixin, Base):
    __tablename__ = "admin_identities"
    subject: Mapped[str] = mapped_column(String(255), primary_key=True)
    role: Mapped[str] = mapped_column(String(30))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class AdminAudit(Base):
    __tablename__ = "admin_audit"
    id: Mapped[int] = mapped_column(primary_key=True)
    subject: Mapped[str] = mapped_column(String(255), index=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    target: Mapped[str] = mapped_column(String(100))
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class ExternalAction(TimestampMixin, Base):
    __tablename__ = "external_actions"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("agent_jobs.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="PENDING")
    result_encrypted: Mapped[str | None] = mapped_column(Text)
