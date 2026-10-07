from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, now


class AgentJob(TimestampMixin, Base):
    __tablename__ = "agent_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(30), default="QUEUED", index=True)
    mode: Mapped[str] = mapped_column(String(20))
    kind: Mapped[str] = mapped_column(String(50), default="AGENT", server_default="AGENT")
    payload_encrypted: Mapped[str | None] = mapped_column(Text)
    request_text: Mapped[str] = mapped_column(Text)  # encrypted user request
    plan_json: Mapped[dict] = mapped_column(JSON, default=dict)  # redacted public summary
    plan_encrypted: Mapped[str | None] = mapped_column(Text)
    current_step: Mapped[int] = mapped_column(Integer, default=0)
    max_steps: Mapped[int] = mapped_column(Integer)
    tool_calls_count: Mapped[int] = mapped_column(Integer, default=0)
    model_requests: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    replan_count: Mapped[int] = mapped_column(Integer, default=0)
    repair_count: Mapped[int] = mapped_column(Integer, default=0)
    validation_runtime_ms: Mapped[int] = mapped_column(Integer, default=0)
    elapsed_ms: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(50))
    failure_message_safe: Mapped[str | None] = mapped_column(String(100))
    result_json: Mapped[dict] = mapped_column(JSON, default=dict)
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger)


class AgentStep(Base):
    __tablename__ = "agent_steps"
    __table_args__ = (UniqueConstraint("job_id", "step_number"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("agent_jobs.id", ondelete="CASCADE"), index=True)
    step_number: Mapped[int] = mapped_column(Integer)
    step_type: Mapped[str] = mapped_column(String(30))
    tool_name: Mapped[str | None] = mapped_column(String(80))
    input_json_redacted: Mapped[dict] = mapped_column(JSON, default=dict)
    output_summary: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(20))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)


class ToolCall(Base):
    __tablename__ = "tool_calls"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("agent_jobs.id", ondelete="CASCADE"), index=True)
    tool_name: Mapped[str] = mapped_column(String(80))
    risk_level: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))
    input_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    output_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Approval(TimestampMixin, Base):
    __tablename__ = "approvals"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("agent_jobs.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    action_type: Mapped[str] = mapped_column(String(30))
    tool_name: Mapped[str] = mapped_column(String(80))
    arguments_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    arguments_hash: Mapped[str] = mapped_column(String(64))
    risk_level: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    step_number: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkspaceChangeSet(TimestampMixin, Base):
    __tablename__ = "workspace_change_sets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[str] = mapped_column(ForeignKey("agent_jobs.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="PROPOSED")
    proposal_encrypted: Mapped[str] = mapped_column(Text)
    diff_encrypted: Mapped[str] = mapped_column(Text)
    summary_json: Mapped[dict] = mapped_column(JSON, default=dict)


class FileSnapshot(Base):
    __tablename__ = "file_snapshots"
    __table_args__ = (UniqueConstraint("change_set_id", "relative_path"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    change_set_id: Mapped[str] = mapped_column(
        ForeignKey("workspace_change_sets.id", ondelete="CASCADE"), index=True
    )
    relative_path: Mapped[str] = mapped_column(String(2048))
    original_sha256: Mapped[str | None] = mapped_column(String(64))
    resulting_sha256: Mapped[str | None] = mapped_column(String(64))
    content_encrypted: Mapped[str | None] = mapped_column(Text)
    existed: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ValidationRun(Base):
    __tablename__ = "validation_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("agent_jobs.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    command_id: Mapped[str] = mapped_column(String(50))
    command_json: Mapped[list] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20))
    exit_code: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    output_encrypted: Mapped[str | None] = mapped_column(Text)
    output_truncated: Mapped[bool] = mapped_column(Boolean, default=False)
    findings_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
