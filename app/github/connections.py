import uuid

from sqlalchemy import select

from app.agent.approvals import utc
from app.core.exceptions import SafeError
from app.core.security import token_hint
from app.db.base import now
from app.db.models.integrations import GitHubConnection, GitHubRepository
from app.github.service import GitHubService
from app.integrations.ownership import IntegrationOwnership
from app.services.audit_service import audit


class GitHubConnections:
    def __init__(self, session, user_id, secrets, settings, http=None):
        self.session, self.user_id, self.secrets, self.settings, self.http = (
            session,
            user_id,
            secrets,
            settings,
            http,
        )
        self.owned = IntegrationOwnership(session, user_id)

    async def create_pat(self, token):
        if not isinstance(token, str) or not token.startswith("github_pat_") or len(token) > 500:
            raise SafeError("INVALID_CREDENTIAL")
        identity = await GitHubService(token, self.http).get_authenticated_identity()
        value = GitHubConnection(
            id=str(uuid.uuid4()),
            user_id=self.user_id,
            connection_type="PAT",
            github_user_id=identity["id"],
            github_login=identity["login"],
            encrypted_token=self.secrets.encrypt(token),
            token_hint=token_hint(token),
            status="ACTIVE",
            last_verified_at=now(),
        )
        self.session.add(value)
        audit(
            self.session, self.user_id, "GITHUB_CONNECTION_CREATED", "github_connection", value.id
        )
        await self.session.flush()
        return value

    async def create_app(self, installation_id, identity, user_token):
        installations = await GitHubService(user_token, self.http).list_installations()
        allowed = [
            x
            for x in installations.get("installations", [])
            if x.get("id") == installation_id and x.get("app_id") == self.settings.github_app_id
        ]
        if not allowed:
            raise SafeError("REPOSITORY_UNAUTHORIZED")
        value = GitHubConnection(
            id=str(uuid.uuid4()),
            user_id=self.user_id,
            connection_type="APP",
            encrypted_token=self.secrets.encrypt(user_token),
            github_user_id=identity["id"],
            github_login=identity["login"],
            installation_id=installation_id,
            status="ACTIVE",
            last_verified_at=now(),
            metadata_json={"verified_user_installation": True},
        )
        self.session.add(value)
        await self.session.flush()
        audit(
            self.session, self.user_id, "GITHUB_CONNECTION_CREATED", "github_connection", value.id
        )
        return value

    async def credential(self, connection, repository_id=None):
        connection = await self.owned.connection(connection.id)
        if connection.connection_type == "PAT":
            return self.secrets.decrypt(connection.encrypted_token)
        # Installation tokens are intentionally not persisted; reuse only within this operation.
        token, expiry = await GitHubService.create_installation_token(
            self.settings, connection.installation_id, self.http, repository_id
        )
        if utc(expiry) <= now():
            raise SafeError("EXPIRED_CREDENTIAL")
        return token

    async def service(self, connection, repository_id=None):
        return GitHubService(await self.credential(connection, repository_id), self.http)

    async def list(self):
        return list(
            await self.session.scalars(
                select(GitHubConnection).where(
                    GitHubConnection.user_id == self.user_id, GitHubConnection.status != "REVOKED"
                )
            )
        )

    async def revoke(self, ident):
        value = await self.owned.connection(ident, False)
        value.status = "REVOKED"
        value.encrypted_token = None
        value.token_hint = None
        repos = list(
            await self.session.scalars(
                select(GitHubRepository).where(GitHubRepository.github_connection_id == ident)
            )
        )
        for repo in repos:
            repo.is_disabled = True
        audit(self.session, self.user_id, "GITHUB_CONNECTION_REVOKED", "github_connection", ident)

    async def sync(self, ident):
        connection = await self.owned.connection(ident)
        service = GitHubService(self.secrets.decrypt(connection.encrypted_token), self.http)
        rows = []
        for page in range(1, 11):
            batch = await service.list_authorized_repositories(
                connection.installation_id if connection.connection_type == "APP" else False, page
            )
            rows.extend(batch)
            if len(batch) < 100:
                break
        else:
            raise SafeError("TOO_MANY_REPOSITORIES")
        known = {
            repo.github_repository_id: repo
            for repo in await self.session.scalars(
                select(GitHubRepository).where(GitHubRepository.github_connection_id == ident)
            )
        }
        for data in rows:
            repo = known.get(data.id)
            if repo is None:
                repo = GitHubRepository(
                    id=str(uuid.uuid4()), github_connection_id=ident, github_repository_id=data.id
                )
                self.session.add(repo)
            repo.owner, repo.name = data.full_name.split("/")
            repo.full_name = data.full_name
            repo.default_branch = data.default_branch
            repo.visibility = "private" if data.private else "public"
            repo.web_url = "https://github.com/" + data.full_name
            repo.clone_url = repo.web_url + ".git"
            repo.is_archived, repo.is_disabled = data.archived, data.disabled
            repo.permissions_json = data.permissions
            repo.last_synced_at = now()
        ids = {row.id for row in rows}
        for data in known.values():
            if data.github_repository_id not in ids:
                data.is_disabled = True
        connection.last_verified_at = now()
        audit(
            self.session,
            self.user_id,
            "GITHUB_REPOSITORIES_SYNCED",
            "github_connection",
            ident,
            count=len(rows),
        )
        await self.session.flush()
        return rows

    async def repositories(self, page=0, query=""):
        rows = list(
            await self.session.scalars(
                select(GitHubRepository)
                .join(GitHubConnection)
                .where(
                    GitHubConnection.user_id == self.user_id,
                    GitHubConnection.status == "ACTIVE",
                    GitHubRepository.is_disabled.is_(False),
                )
                .order_by(GitHubRepository.full_name)
            )
        )
        if query:
            rows = [row for row in rows if query.casefold() in row.full_name.casefold()]
        return rows[page * 10 : page * 10 + 10], len(rows)

    async def verify_repository(self, repo):
        repo = await self.owned.repository(repo.id)
        connection = await self.owned.connection(repo.github_connection_id)
        discovery = GitHubService(self.secrets.decrypt(connection.encrypted_token), self.http)
        live = await discovery.get_repository(repo.full_name)
        # Reprove installation/token authorization; public metadata alone is never proof.
        authorized = False
        for page in range(1, 11):
            rows = await discovery.list_authorized_repositories(
                connection.installation_id if connection.connection_type == "APP" else False, page
            )
            if any(x.id == live.id for x in rows):
                authorized = True
                break
            if len(rows) < 100:
                break
        if not authorized or live.id != repo.github_repository_id or live.archived or live.disabled:
            raise SafeError("REPOSITORY_UNAUTHORIZED")
        repo.default_branch = live.default_branch
        repo.permissions_json = live.permissions
        service = await self.service(connection, repo.github_repository_id)
        return repo, connection, service
