import hashlib
import json
import uuid
from datetime import timedelta, timezone

from sqlalchemy import select

from app.agent.ownership import AgentOwnership
from app.core.exceptions import SafeError
from app.db.base import now
from app.db.models.agent import Approval
from app.services.audit_service import audit

TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "LIMIT_REACHED"}


def arguments_hash(tool_name, arguments):
    return hashlib.sha256(
        json.dumps(
            {"tool": tool_name, "arguments": arguments}, sort_keys=True, ensure_ascii=False
        ).encode()
    ).hexdigest()


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


class ApprovalService:
    def __init__(self, session, user_id, settings):
        self.session, self.user_id, self.settings = session, user_id, settings
        self.owned = AgentOwnership(session, user_id)

    async def request(self, job, tool_name, arguments, risk, summary):
        await self.owned.job(job.id)
        fingerprint = arguments_hash(tool_name, arguments)
        existing = await self.session.scalar(
            select(Approval).where(
                Approval.job_id == job.id,
                Approval.step_number == job.current_step,
                Approval.arguments_hash == fingerprint,
                Approval.status == "PENDING",
            )
        )
        if existing and utc(existing.expires_at) > now():
            return existing
        if existing:
            existing.status = "EXPIRED"
        value = Approval(
            id=str(uuid.uuid4()),
            job_id=job.id,
            user_id=self.user_id,
            action_type="TOOL_EXECUTION",
            tool_name=tool_name,
            arguments_summary=summary,
            arguments_hash=fingerprint,
            risk_level=str(risk),
            status="PENDING",
            step_number=job.current_step,
            expires_at=now() + timedelta(seconds=self.settings.approval_ttl_seconds),
        )
        self.session.add(value)
        job.status = "WAITING_APPROVAL"
        audit(
            self.session, self.user_id, "APPROVAL_REQUESTED", "approval", value.id, status="PENDING"
        )
        await self.session.flush()
        return value

    async def decide(self, ident, approve):
        value = await self.owned.approval(ident, True)
        job = await self.owned.job(value.job_id, True)
        if (
            value.status != "PENDING"
            or job.status != "WAITING_APPROVAL"
            or value.step_number != job.current_step
        ):
            raise SafeError("STALE_APPROVAL")
        if utc(value.expires_at) <= now():
            value.status = "EXPIRED"
            job.status = "FAILED"
            job.failure_code = "EXPIRED_APPROVAL"
            await self.session.commit()
            raise SafeError("EXPIRED_APPROVAL")
        value.status = "APPROVED" if approve else "REJECTED"
        value.decided_at = now()
        job.status = "QUEUED" if approve else "FAILED"
        if not approve:
            job.failure_code = "APPROVAL_REJECTED"
            job.failure_message_safe = "APPROVAL_REJECTED"
        audit(
            self.session,
            self.user_id,
            "APPROVAL_APPROVED" if approve else "APPROVAL_REJECTED",
            "approval",
            value.id,
            status=value.status,
        )
        return value

    async def approved(self, job, tool_name, arguments):
        value = await self.session.scalar(
            select(Approval).where(
                Approval.job_id == job.id,
                Approval.user_id == self.user_id,
                Approval.step_number == job.current_step,
                Approval.arguments_hash == arguments_hash(tool_name, arguments),
                Approval.status == "APPROVED",
            )
        )
        return bool(value and utc(value.expires_at) > now())
