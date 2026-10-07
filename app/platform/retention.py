from datetime import timedelta

from sqlalchemy import delete, select

from app.agent.approvals import TERMINAL
from app.core.exceptions import SafeError
from app.db.base import now
from app.db.models import AuditLog, Model, Provider, User, UserSetting
from app.db.models.agent import AgentJob
from app.db.models.integrations import GitHubConnection, MCPServer, OAuthState
from app.db.models.platform import MemoryItem, UsageEntry, UserPlan
from app.db.models.projects import Workspace
from app.services.workspace_service import WorkspaceService


class RetentionService:
    def __init__(self, session, settings, secrets, limits):
        self.session, self.settings, self.secrets, self.limits = session, settings, secrets, limits

    async def sweep(self):
        async with self.limits.lock("platform:retention", 120):
            return await self._sweep()

    async def _sweep(self):
        stamp = now()
        await self.session.execute(
            delete(MemoryItem).where(
                (MemoryItem.expires_at <= stamp)
                | (
                    MemoryItem.updated_at
                    < stamp - timedelta(days=getattr(self.settings, "memory_retention_days", 90))
                )
            )
        )
        await self.session.execute(delete(OAuthState).where(OAuthState.expires_at <= stamp))
        jobs = list(
            await self.session.scalars(
                select(AgentJob).where(
                    AgentJob.status.in_(TERMINAL),
                    AgentJob.completed_at
                    < stamp - timedelta(days=getattr(self.settings, "artifact_retention_days", 30)),
                )
            )
        )
        for job in jobs:
            await self.session.delete(job)
        workspaces = list(
            await self.session.scalars(
                select(Workspace).where(
                    Workspace.status != "DELETED",
                    Workspace.last_accessed_at
                    < stamp
                    - timedelta(days=getattr(self.settings, "workspace_retention_days", 30)),
                )
            )
        )
        removed = 0
        for workspace in workspaces:
            w = WorkspaceService(
                self.session, workspace.user_id, self.settings, self.secrets, self.limits
            )
            try:
                await w.delete(workspace.id)
                removed += 1
            except SafeError as error:
                if error.code != "WORKSPACE_BUSY":
                    raise
        # Audit has a separate longer policy; no admin UI deletion endpoint exists.
        await self.session.execute(
            delete(AuditLog).where(
                AuditLog.created_at
                < stamp - timedelta(days=getattr(self.settings, "audit_retention_days", 365))
            )
        )
        await self.session.commit()
        return {"expired_jobs": len(jobs), "removed_workspaces": removed}

    async def delete_user_data(self, user_id):
        user = await self.session.get(User, user_id, with_for_update=True)
        if not user:
            raise SafeError("NOT_FOUND")
        user.is_active = False
        active = list(
            await self.session.scalars(
                select(AgentJob).where(
                    AgentJob.user_id == user_id, AgentJob.status.not_in(TERMINAL)
                )
            )
        )
        if active:
            for job in active:
                await self.limits.redis.set("agent:cancel:" + job.id, "1", ex=3600)
            await self.session.commit()
            raise SafeError("WORKSPACE_BUSY")
        w = WorkspaceService(self.session, user_id, self.settings, self.secrets, self.limits)
        for workspace in await self.session.scalars(
            select(Workspace).where(Workspace.user_id == user_id, Workspace.status != "DELETED")
        ):
            await w.delete(workspace.id)
        for model in [
            AgentJob,
            MemoryItem,
            UsageEntry,
            UserSetting,
            UserPlan,
            OAuthState,
            GitHubConnection,
            MCPServer,
        ]:
            await self.session.execute(delete(model).where(model.user_id == user_id))
        # Explicit model deletion also removes stale active selections and handles SQLite/Postgres alike.
        await self.session.execute(
            delete(Model).where(
                Model.provider_id.in_(select(Provider.id).where(Provider.user_id == user_id))
            )
        )
        await self.session.execute(delete(Provider).where(Provider.user_id == user_id))
        await self.session.execute(delete(Workspace).where(Workspace.user_id == user_id))
        user.telegram_username = user.first_name = user.last_name = None
        # Minimal tombstone preserves immutable audit FK; identity is no longer an active account.
        user.telegram_user_id = -user.id
        self.session.add(
            AuditLog(
                user_id=user_id,
                action="USER_DATA_DELETED",
                entity_type="user",
                entity_id=str(user_id),
                metadata_json={},
            )
        )
        await self.session.commit()
