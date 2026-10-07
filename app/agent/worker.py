import asyncio
from contextlib import suppress

from sqlalchemy import or_, select

from app.agent.approvals import utc
from app.agent.orchestrator import AgentOrchestrator
from app.agent.patches import PatchEngine
from app.core.exceptions import SafeError
from app.db.base import now
from app.db.models import User
from app.db.models.agent import AgentJob, Approval, WorkspaceChangeSet
from app.services.model_service import ModelService
from app.services.provider_service import ProviderService
from app.services.workspace_service import WorkspaceService


class AgentWorker:
    def __init__(self, sessions, secrets, http, limits, settings, notify=None):
        self.sessions, self.secrets, self.http, self.limits, self.settings, self.notify = (
            sessions,
            secrets,
            http,
            limits,
            settings,
            notify,
        )
        self.stopping = False

    def services(self, session, user_id):
        workspace = WorkspaceService(session, user_id, self.settings, self.secrets, self.limits)
        models = ModelService(
            ProviderService(
                session, user_id, self.secrets, self.http, self.limits, self.settings.max_models
            ),
            self.settings,
        )
        return workspace, models

    async def recover(self):
        async with self.sessions() as session:
            interrupted = list(
                await session.scalars(
                    select(AgentJob).where(
                        or_(
                            AgentJob.status.in_(
                                ["PLANNING", "RUNNING", "RECOVERING", "CANCEL_REQUESTED"]
                            ),
                            AgentJob.id.in_(
                                select(WorkspaceChangeSet.job_id).where(
                                    WorkspaceChangeSet.status == "APPLYING"
                                )
                            ),
                        )
                    )
                )
            )
            for job in interrupted:
                job.status = "RECOVERING"
                await session.commit()
                workspace, _ = self.services(session, job.user_id)
                changes = list(
                    await session.scalars(
                        select(WorkspaceChangeSet).where(
                            WorkspaceChangeSet.job_id == job.id,
                            WorkspaceChangeSet.status == "APPLYING",
                        )
                    )
                )
                try:
                    for change in changes:
                        await PatchEngine(workspace, job).rollback(change.id, recovery=True)
                    job.failure_code = "WORKER_INTERRUPTED"
                except SafeError:
                    job.failure_code = "RECOVERY_REQUIRES_REVIEW"
                job.status = "FAILED"
                if job.kind != "AGENT":
                    job.payload_encrypted = None
                job.failure_message_safe = job.failure_code
                job.completed_at = now()
                await session.commit()

    async def expire(self, session):
        approvals = list(
            await session.scalars(select(Approval).where(Approval.status == "PENDING"))
        )
        for value in approvals:
            if utc(value.expires_at) <= now():
                value.status = "EXPIRED"
                job = await session.get(AgentJob, value.job_id)
                if job and job.status == "WAITING_APPROVAL":
                    job.status = "FAILED"
                    job.failure_code = "EXPIRED_APPROVAL"
                    job.completed_at = now()
        await session.commit()

    async def run_once(self):
        async with self.sessions() as session:
            await self.expire(session)
            job = await session.scalar(
                select(AgentJob)
                .where(AgentJob.status == "QUEUED")
                .order_by(AgentJob.created_at)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if not job:
                return False
            user = await session.get(User, job.user_id)
            if not user or not user.is_active:
                job.status = "FAILED"
                job.failure_code = "INACTIVE"
                job.payload_encrypted = None
                job.completed_at = now()
                await session.commit()
                return True
            job.status = "PLANNING"
            await session.commit()
            from app.platform.telemetry import metric, trace_context

            metric(
                "worker_lag",
                max(0, (now() - job.created_at.replace(tzinfo=now().tzinfo)).total_seconds()),
                observe=True,
            )
            with trace_context(user_id=job.user_id, job_id=job.id, workspace_id=job.workspace_id):
                return await self.execute_job(session, job)

    async def execute_job(self, session, job):
        workspace, models = self.services(session, job.user_id)
        if job.kind != "AGENT":
            from app.integrations.jobs import IntegrationJobExecutor

            await IntegrationJobExecutor(workspace, self.notify).run(job)
        else:
            await AgentOrchestrator(workspace, models, notify=self.notify).run(job.id)
        return True

    async def run(self):
        # Standby replicas never recover a job owned by the live lease holder.
        key = "agent:worker:lease"
        while not self.stopping:
            try:
                async with self.limits.lock(key, 60):
                    redis_key = "lock:" + key
                    token = await self.limits.redis.get(redis_key)
                    owner = asyncio.current_task()
                    heartbeat = asyncio.create_task(self._heartbeat(redis_key, token, owner))
                    try:
                        await self.recover()
                        while not self.stopping:
                            if not await self.run_once():
                                await asyncio.sleep(1)
                    finally:
                        heartbeat.cancel()
                        with suppress(asyncio.CancelledError):
                            await heartbeat
            except SafeError as error:
                if error.code != "RATE_LIMITED":
                    raise
                await asyncio.sleep(2)

    async def _heartbeat(self, key, token, owner):
        while True:
            await asyncio.sleep(20)
            script = "if redis.call('get',KEYS[1]) == ARGV[1] then return redis.call('expire',KEYS[1],60) else return 0 end"
            try:
                renewed = await self.limits.redis.eval(script, 1, key, token)
            except Exception:
                renewed = False
            if not renewed:
                self.stopping = True
                owner.cancel()
                return
