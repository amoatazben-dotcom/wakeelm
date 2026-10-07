import time
from datetime import datetime
from urllib.parse import quote

import jwt

from app.core.exceptions import SafeError
from app.github.schemas import RepositoryMetadata, full_name
from app.integrations.http import IntegrationHTTP


class GitHubService:
    def __init__(self, token, http=None):
        self.token, self.http = token, http or IntegrationHTTP()

    async def request(self, method, path, payload=None):
        return await self.http.request(
            method,
            "https://api.github.com" + path,
            headers={
                "Authorization": "Bearer " + self.token,
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json_body=payload,
        )

    async def get_authenticated_identity(self):
        return await self.request("GET", "/user")

    async def list_installations(self, page=1):
        return await self.request("GET", f"/user/installations?per_page=100&page={self.page(page)}")

    def page(self, value):
        if not isinstance(value, int) or not 1 <= value <= 1000:
            raise SafeError("INVALID_INPUT")
        return value

    async def list_authorized_repositories(self, installation=False, page=1):
        value = await self.request(
            "GET",
            (
                f"/user/installations/{int(installation)}/repositories"
                if installation
                else "/user/repos"
            )
            + f"?per_page=100&page={self.page(page)}",
        )
        rows = value.get("repositories", []) if isinstance(value, dict) else value
        return [RepositoryMetadata.model_validate(row) for row in rows]

    async def get_repository(self, repo):
        return RepositoryMetadata.model_validate(
            await self.request("GET", "/repos/" + full_name(repo))
        )

    async def list_branches(self, repo, page=1):
        return await self.request(
            "GET", f"/repos/{full_name(repo)}/branches?per_page=100&page={self.page(page)}"
        )

    async def get_default_branch(self, repo):
        return (await self.get_repository(repo)).default_branch

    async def get_branch(self, repo, branch):
        return await self.request(
            "GET", f"/repos/{full_name(repo)}/branches/{quote(branch, safe='')}"
        )

    async def get_branch_protection_summary(self, repo, branch):
        value = await self.get_branch(repo, branch)
        return {"branch": branch, "protected": bool(value.get("protected"))}

    async def get_issue(self, repo, number):
        return await self.request("GET", f"/repos/{full_name(repo)}/issues/{self.number(number)}")

    async def list_issues(self, repo, page=1):
        return await self.request(
            "GET", f"/repos/{full_name(repo)}/issues?per_page=100&page={self.page(page)}"
        )

    async def get_pull_request(self, repo, number):
        return await self.request("GET", f"/repos/{full_name(repo)}/pulls/{self.number(number)}")

    async def list_pull_requests(self, repo, page=1):
        return await self.request(
            "GET", f"/repos/{full_name(repo)}/pulls?per_page=100&page={self.page(page)}"
        )

    async def compare_refs(self, repo, base, head):
        return await self.request(
            "GET",
            f"/repos/{full_name(repo)}/compare/{quote(base, safe='')}...{quote(head, safe='')}",
        )

    async def get_commit(self, repo, sha):
        return await self.request("GET", f"/repos/{full_name(repo)}/commits/{quote(sha, safe='')}")

    async def create_pull_request(self, repo, head, base, data):
        return await self.request(
            "POST", f"/repos/{full_name(repo)}/pulls", {"head": head, "base": base, **data}
        )

    async def create_issue_comment(self, repo, number, body):
        return await self.request(
            "POST",
            f"/repos/{full_name(repo)}/issues/{self.number(number)}/comments",
            {"body": body},
        )

    async def create_pull_request_comment(self, repo, number, body):
        return await self.create_issue_comment(repo, number, body)

    async def checks(self, repo, sha):
        return await self.request(
            "GET", f"/repos/{full_name(repo)}/commits/{quote(sha, safe='')}/check-runs"
        )

    async def actions(self, repo):
        return await self.request("GET", f"/repos/{full_name(repo)}/actions/runs?per_page=10")

    async def statuses(self, repo, sha):
        return await self.request(
            "GET", f"/repos/{full_name(repo)}/commits/{quote(sha, safe='')}/status"
        )

    @staticmethod
    def number(value):
        if not isinstance(value, int) or value < 1:
            raise SafeError("INVALID_INPUT")
        return value

    @staticmethod
    async def create_installation_token(settings, installation_id, http=None, repository_id=None):
        if not settings.github_app_id or not settings.github_app_private_key or not installation_id:
            raise SafeError("GITHUB_APP_UNCONFIGURED")
        issued = int(time.time())
        bearer = jwt.encode(
            {"iat": issued - 30, "exp": issued + 540, "iss": str(settings.github_app_id)},
            settings.github_app_private_key.get_secret_value(),
            algorithm="RS256",
        )
        permissions = {
            "metadata": "read",
            "contents": "write" if settings.github_write_enabled else "read",
            "pull_requests": "write" if settings.github_write_enabled else "read",
            "issues": "write" if settings.github_comments_enabled else "read",
            "actions": "read",
            "checks": "read",
            "statuses": "read",
        }
        result = await (http or IntegrationHTTP()).request(
            "POST",
            f"https://api.github.com/app/installations/{int(installation_id)}/access_tokens",
            headers={"Authorization": "Bearer " + bearer, "Accept": "application/vnd.github+json"},
            json_body={
                "permissions": permissions,
                **({"repository_ids": [int(repository_id)]} if repository_id else {}),
            },
        )
        if not isinstance(result.get("token"), str) or not result.get("expires_at"):
            raise SafeError("INVALID_RESPONSE")
        return result["token"], datetime.fromisoformat(result["expires_at"].replace("Z", "+00:00"))
