import hashlib
import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import or_, select

from app.agent.ownership import AgentOwnership
from app.core.exceptions import SafeError
from app.db.base import now
from app.db.models.platform import MemoryItem
from app.db.models.projects import Workspace


class MemoryCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    layer: str = Field(pattern="^(CONVERSATION|PROJECT|PREFERENCE|TASK|EXECUTION|KNOWLEDGE)$")
    content: str = Field(min_length=1, max_length=12000)
    workspace_id: str | None = None
    job_id: str | None = None
    source_type: str = Field(
        pattern="^(USER|PROJECT_FILE|TOOL_RESULT|SYSTEM|MODEL_INFERENCE|MCP_RESOURCE)$"
    )
    source_id: str = Field(min_length=1, max_length=200)
    uri: str | None = Field(default=None, max_length=2048)
    confidence: float = Field(default=0.5, ge=0, le=1)
    expires_at: datetime | None = None
    approved: bool = False

    @model_validator(mode="after")
    def scope(self):
        if self.layer in {"PROJECT", "KNOWLEDGE"} and not self.workspace_id:
            raise ValueError("Workspace scope required")
        if self.layer in {"TASK", "EXECUTION"} and not self.job_id:
            raise ValueError("Job scope required")
        return self


class MemoryService:
    def __init__(self, session, user_id, secrets):
        self.session, self.user_id, self.secrets = session, user_id, secrets

    async def validate_scope(self, workspace_id=None, job_id=None):
        if workspace_id:
            workspace = await self.session.scalar(
                select(Workspace).where(
                    Workspace.id == workspace_id,
                    Workspace.user_id == self.user_id,
                    Workspace.status != "DELETED",
                )
            )
            if workspace is None:
                raise SafeError("NOT_FOUND")
        if job_id:
            job = await AgentOwnership(self.session, self.user_id).job(job_id)
            if workspace_id and job.workspace_id != workspace_id:
                raise SafeError("NOT_FOUND")

    async def write(self, candidate):
        await self.validate_scope(candidate.workspace_id, candidate.job_id)
        if candidate.source_type == "MODEL_INFERENCE" and not candidate.approved:
            raise SafeError("POLICY_DENIED")
        from app.platform.redaction import user_sanitizer

        sanitizer = await user_sanitizer(self.session, self.user_id, self.secrets)
        if sanitizer.clean(candidate.content) != candidate.content:
            raise SafeError("MEMORY_SECRET_DENIED")
        # Search terms are not persisted in clear text. Retrieval decrypts only owned bounded rows.
        scope = f"{candidate.layer}:{candidate.workspace_id or ''}:{candidate.job_id or ''}"
        digest = hashlib.sha256(candidate.content.encode()).hexdigest()
        existing = await self.session.scalar(
            select(MemoryItem).where(
                MemoryItem.user_id == self.user_id,
                MemoryItem.scope_key == scope,
                MemoryItem.digest == digest,
            )
        )
        if existing:
            return existing
        row = MemoryItem(
            user_id=self.user_id,
            workspace_id=candidate.workspace_id,
            job_id=candidate.job_id,
            layer=candidate.layer,
            scope_key=scope,
            digest=digest,
            content_encrypted=self.secrets.encrypt(candidate.content),
            confidence=min(candidate.confidence, 0.5)
            if candidate.source_type == "MODEL_INFERENCE"
            else candidate.confidence,
            provenance_json={
                "source_type": candidate.source_type,
                "source_id": candidate.source_id,
                "uri": candidate.uri,
                "timestamp": now().isoformat(),
                "trust_level": "UNTRUSTED",
                "retrieval_method": "EXACT_SCOPED",
            },
            expires_at=candidate.expires_at,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def retrieve(self, query, workspace_id=None, job_id=None, layers=None, limit=8):
        await self.validate_scope(workspace_id, job_id)
        stmt = select(MemoryItem).where(
            MemoryItem.user_id == self.user_id,
            or_(MemoryItem.expires_at.is_(None), MemoryItem.expires_at > now()),
            MemoryItem.workspace_id == workspace_id
            if workspace_id
            else MemoryItem.workspace_id.is_(None),
            MemoryItem.job_id == job_id if job_id else MemoryItem.job_id.is_(None),
        )
        if layers:
            stmt = stmt.where(MemoryItem.layer.in_(layers))
        rows = list(
            await self.session.scalars(
                stmt.order_by(MemoryItem.updated_at.desc(), MemoryItem.id.desc()).limit(200)
            )
        )
        terms = set(re.findall(r"\w{3,}", query.lower()))
        ranked = []
        for position, row in enumerate(rows):
            content = self.secrets.decrypt(row.content_encrypted)
            matches = len(terms & set(re.findall(r"\w{3,}", content.lower())))
            if matches or row.layer == "PREFERENCE":
                score = matches * 10 + float(row.confidence) + 1 / (position + 1)
                ranked.append((score, row, content))
        return [
            {
                "id": row.id,
                "content": content,
                "confidence": float(row.confidence),
                "scope": row.scope_key,
                "provenance": row.provenance_json,
            }
            for _, row, content in sorted(ranked, key=lambda item: -item[0])[
                : min(20, max(1, limit))
            ]
        ]

    async def conversation(self, text, source_id):
        await self.write(
            MemoryCandidate(
                layer="CONVERSATION",
                content=text[:12000],
                source_type="USER",
                source_id=source_id,
                confidence=1,
            )
        )
        rows = list(
            await self.session.scalars(
                select(MemoryItem)
                .where(MemoryItem.user_id == self.user_id, MemoryItem.layer == "CONVERSATION")
                .order_by(MemoryItem.id.desc())
            )
        )
        # Progressive extractive compaction, clearly labelled rather than invented decisions.
        if len(rows) > 12:
            old = rows[6:]
            summary = "EXTRACTIVE_HISTORY\n" + "\n".join(
                self.secrets.decrypt(row.content_encrypted)[-500:] for row in reversed(old[:12])
            )
            for row in old:
                await self.session.delete(row)
            await self.session.flush()
            await self.write(
                MemoryCandidate(
                    layer="CONVERSATION",
                    content=summary[:12000],
                    source_type="SYSTEM",
                    source_id="progressive-history",
                    confidence=0.7,
                )
            )
