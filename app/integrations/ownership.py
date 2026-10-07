from sqlalchemy import select

from app.core.exceptions import SafeError
from app.db.models.integrations import (
    GitHubConnection,
    GitHubRepository,
    MCPServer,
    MCPTool,
    RepositoryWorkspace,
)
from app.db.models.projects import Workspace


class IntegrationOwnership:
    def __init__(self, session, user_id):
        self.session, self.user_id = session, user_id

    async def connection(self, ident, active=True):
        value = await self.session.scalar(
            select(GitHubConnection).where(
                GitHubConnection.id == ident, GitHubConnection.user_id == self.user_id
            )
        )
        if not value or active and value.status != "ACTIVE":
            raise SafeError("NOT_FOUND")
        return value

    async def repository(self, ident):
        value = await self.session.scalar(
            select(GitHubRepository)
            .join(GitHubConnection)
            .where(
                GitHubRepository.id == ident,
                GitHubConnection.user_id == self.user_id,
                GitHubConnection.status == "ACTIVE",
                GitHubRepository.is_disabled.is_(False),
            )
        )
        if not value:
            raise SafeError("NOT_FOUND")
        return value

    async def repository_workspace(self, workspace_id):
        value = await self.session.scalar(
            select(RepositoryWorkspace)
            .join(Workspace)
            .where(
                RepositoryWorkspace.workspace_id == workspace_id,
                RepositoryWorkspace.user_id == self.user_id,
                Workspace.user_id == self.user_id,
                Workspace.status != "DELETED",
            )
        )
        if not value:
            raise SafeError("NOT_FOUND")
        repository = await self.repository(value.github_repository_id)
        connection = await self.connection(value.connection_id)
        if repository.github_connection_id != connection.id:
            raise SafeError("POLICY_DENIED")
        return value, repository, connection

    async def server(self, ident, active=True):
        value = await self.session.scalar(
            select(MCPServer).where(
                MCPServer.id == ident,
                MCPServer.user_id == self.user_id,
                MCPServer.status != "REMOVED",
            )
        )
        if not value or active and value.status != "CONNECTED":
            raise SafeError("NOT_FOUND")
        return value

    async def tool(self, ident):
        value = await self.session.scalar(
            select(MCPTool)
            .join(MCPServer)
            .where(
                MCPTool.id == ident,
                MCPServer.user_id == self.user_id,
                MCPServer.status == "CONNECTED",
            )
        )
        if not value or not value.is_enabled:
            raise SafeError("TOOL_DISABLED")
        return value
