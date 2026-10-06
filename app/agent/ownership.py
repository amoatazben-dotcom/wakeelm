from sqlalchemy import select

from app.core.exceptions import SafeError
from app.db.models.agent import AgentJob, Approval, WorkspaceChangeSet
from app.db.models.projects import Workspace


class AgentOwnership:
    def __init__(self, session, user_id):
        self.session, self.user_id = session, user_id

    async def job(self, job_id, for_update=False):
        query = (
            select(AgentJob)
            .join(Workspace)
            .where(
                AgentJob.id == job_id,
                AgentJob.user_id == self.user_id,
                Workspace.user_id == self.user_id,
                Workspace.status != "DELETED",
            )
        )
        if for_update:
            query = query.with_for_update(of=AgentJob)
        value = await self.session.scalar(query)
        if value is None:
            raise SafeError("NOT_FOUND")
        return value

    async def approval(self, approval_id, for_update=False):
        query = (
            select(Approval)
            .join(AgentJob)
            .join(Workspace)
            .where(
                Approval.id == approval_id,
                Approval.user_id == self.user_id,
                AgentJob.user_id == self.user_id,
                Workspace.user_id == self.user_id,
                Workspace.status != "DELETED",
            )
        )
        if for_update:
            query = query.with_for_update(of=Approval)
        value = await self.session.scalar(query)
        if value is None:
            raise SafeError("NOT_FOUND")
        return value

    async def change_set(self, ident):
        value = await self.session.scalar(
            select(WorkspaceChangeSet)
            .join(AgentJob)
            .join(Workspace, Workspace.id == WorkspaceChangeSet.workspace_id)
            .where(
                WorkspaceChangeSet.id == ident,
                AgentJob.user_id == self.user_id,
                Workspace.user_id == self.user_id,
                Workspace.status != "DELETED",
            )
        )
        if value is None:
            raise SafeError("NOT_FOUND")
        return value
