import uuid

from sqlalchemy import select, update

from app.agent.approvals import TERMINAL, ApprovalService
from app.agent.ownership import AgentOwnership
from app.agent.patches import PatchEngine
from app.agent.schemas import AgentMode, AgentPlan, ToolRequest
from app.core.exceptions import SafeError
from app.db.base import now
from app.db.models.agent import AgentJob, Approval, WorkspaceChangeSet
from app.services.audit_service import audit


class AgentService:
    def __init__(self, workspaces, models):
        self.w, self.models = workspaces, models
        self.owned = AgentOwnership(workspaces.session, workspaces.user_id)
        self.approvals = ApprovalService(
            workspaces.session, workspaces.user_id, workspaces.settings
        )

    async def create(self, workspace_id, mode, request, chat_id=None):
        workspace = await self.w.owned(workspace_id, True)
        try:
            mode = AgentMode(mode)
        except ValueError:
            raise SafeError("INVALID_INPUT") from None
        if not isinstance(request, str) or not request.strip() or len(request) > 16000:
            raise SafeError("INVALID_INPUT")
        if workspace.status != "READY":
            raise SafeError("WORKSPACE_BUSY")
        active = await self.w.session.scalar(
            select(AgentJob.id).where(
                AgentJob.workspace_id == workspace_id, AgentJob.status.not_in(TERMINAL)
            )
        )
        if active:
            raise SafeError("WORKSPACE_BUSY")
        await self.w.idle(workspace_id)
        await self.models.active()
        job = AgentJob(
            id=str(uuid.uuid4()),
            user_id=self.w.user_id,
            workspace_id=workspace_id,
            mode=mode,
            request_text=self.w.secrets.encrypt(request),
            max_steps=self.w.settings.max_agent_steps,
            status="QUEUED",
            telegram_chat_id=chat_id,
        )
        self.w.session.add(job)
        await self.w.session.flush()
        audit(
            self.w.session,
            self.w.user_id,
            "AGENT_JOB_CREATED",
            "agent_job",
            job.id,
            status="QUEUED",
        )
        return job

    async def cancel(self, ident):
        job = await self.owned.job(ident, True)
        if job.status in TERMINAL:
            raise SafeError("JOB_FINISHED")
        await self.w.limits.redis.set(
            "agent:cancel:" + job.id, "1", ex=self.w.settings.max_task_duration + 3600
        )
        job.status = (
            "CANCEL_REQUESTED"
            if job.status in {"RUNNING", "PLANNING", "RECOVERING"}
            else "CANCELLED"
        )
        job.cancelled_at = now()
        if job.status == "CANCELLED":
            job.completed_at = now()
        await self.w.session.execute(
            update(Approval)
            .where(Approval.job_id == job.id, Approval.status == "PENDING")
            .values(status="CANCELLED", decided_at=now())
        )
        audit(
            self.w.session,
            self.w.user_id,
            "AGENT_JOB_CANCELLED",
            "agent_job",
            job.id,
            status=job.status,
        )
        return job

    async def jobs(self, workspace_id):
        await self.w.owned(workspace_id)
        return list(
            await self.w.session.scalars(
                select(AgentJob)
                .where(AgentJob.workspace_id == workspace_id, AgentJob.user_id == self.w.user_id)
                .order_by(AgentJob.created_at.desc())
                .limit(10)
            )
        )

    async def pending(self, ident):
        job = await self.owned.job(ident)
        return list(
            await self.w.session.scalars(
                select(Approval).where(Approval.job_id == job.id, Approval.status == "PENDING")
            )
        )

    async def changes(self, workspace_id):
        await self.w.owned(workspace_id)
        return list(
            await self.w.session.scalars(
                select(WorkspaceChangeSet)
                .where(WorkspaceChangeSet.workspace_id == workspace_id)
                .order_by(WorkspaceChangeSet.created_at.desc())
                .limit(10)
            )
        )

    async def accept_change(self, ident):
        value = await self.owned.change_set(ident)
        job = await self.owned.job(value.job_id, True)
        # Explicit user action may turn a finished suggestion into a workspace task.
        if job.status != "COMPLETED" or value.status != "PROPOSED" or job.mode != "SUGGEST":
            raise SafeError("STALE_FILE")
        await self.w.owned(job.workspace_id, True)
        active = await self.w.session.scalar(
            select(AgentJob.id).where(
                AgentJob.workspace_id == job.workspace_id, AgentJob.status.not_in(TERMINAL)
            )
        )
        if active:
            raise SafeError("WORKSPACE_BUSY")
        if job.current_step >= job.max_steps:
            raise SafeError("AGENT_LIMIT")
        plan = AgentPlan.model_validate_json(self.w.secrets.decrypt(job.plan_encrypted))
        plan.steps.append(
            ToolRequest(
                tool_name="workspace.apply_patch",
                arguments={"change_set_id": ident},
                reason="EXPLICIT_USER_APPLY",
            )
        )
        plan.complete = True
        job.mode = "WORKSPACE"
        job.status = "QUEUED"
        job.completed_at = None
        job.plan_encrypted = self.w.secrets.encrypt(plan.model_dump_json())
        job.plan_json = {
            "tools": [step.tool_name for step in plan.steps],
            "risk": value.summary_json["risk"],
        }
        audit(
            self.w.session,
            self.w.user_id,
            "AGENT_MODE_CHANGED",
            "agent_job",
            job.id,
            status="WORKSPACE",
        )
        return job

    async def restore(self, ident):
        value = await self.owned.change_set(ident)
        job = await self.owned.job(value.job_id, True)
        if job.status not in TERMINAL:
            raise SafeError("WORKSPACE_BUSY")
        await self.w.owned(job.workspace_id, True)
        active = await self.w.session.scalar(
            select(AgentJob.id).where(
                AgentJob.workspace_id == job.workspace_id, AgentJob.status.not_in(TERMINAL)
            )
        )
        if active:
            raise SafeError("WORKSPACE_BUSY")
        return await PatchEngine(self.w, job).rollback(ident)

    async def enqueue_action(self, ident, request):
        job = await self.owned.job(ident, True)
        if job.kind != "AGENT" or job.status != "COMPLETED" or job.mode != "WORKSPACE":
            raise SafeError("JOB_FINISHED")
        if request.tool_name not in {"git.commit", "git.push_branch", "github.create_pull_request"}:
            raise SafeError("POLICY_DENIED")
        await self.w.owned(job.workspace_id, True)
        await self.w.idle(job.workspace_id)
        if job.current_step >= job.max_steps:
            raise SafeError("AGENT_LIMIT")
        plan = AgentPlan.model_validate_json(self.w.secrets.decrypt(job.plan_encrypted))
        plan.steps.append(request)
        plan.complete = True
        plan.answer = ""
        job.plan_encrypted = self.w.secrets.encrypt(plan.model_dump_json())
        job.plan_json = {"tools": [step.tool_name for step in plan.steps], "risk": "HIGH"}
        job.status = "QUEUED"
        job.completed_at = None
        return job

    async def resume_after_auth(self, ident):
        job = await self.owned.job(ident, True)
        if (
            job.kind != "AGENT"
            or job.status != "FAILED"
            or job.failure_code not in {"SCOPE_REQUIRED", "AUTH_REQUIRED", "AUTH_FAILED"}
        ):
            raise SafeError("JOB_FINISHED")
        from app.integrations.ownership import IntegrationOwnership

        await IntegrationOwnership(self.w.session, self.w.user_id).server(
            job.result_json.get("auth_server_id", "")
        )
        await self.w.owned(job.workspace_id, True)
        await self.w.idle(job.workspace_id)
        if job.current_step >= job.max_steps:
            raise SafeError("AGENT_LIMIT")
        job.status = "QUEUED"
        job.failure_code = job.failure_message_safe = None
        job.completed_at = None
        audit(self.w.session, self.w.user_id, "AGENT_AUTH_RESUMED", "agent_job", job.id)
        return job
