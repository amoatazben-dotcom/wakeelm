import hashlib
import json
import re
import uuid

from sqlalchemy import select

from app.core.exceptions import SafeError
from app.db.base import now
from app.db.models.agent import ValidationRun
from app.db.models.integrations import RepositoryWorkspace
from app.db.models.projects import Workspace
from app.git.runtime import ControlledGitService, agent_branch
from app.git.scanner import RepositorySafetyScanner
from app.github.connections import GitHubConnections
from app.integrations.ownership import IntegrationOwnership
from app.integrations.sanitizer import ExternalToolOutputSanitizer
from app.services.audit_service import audit


async def workspace_digest(w, wid):
    values = []
    for path in w.storage.list_files(w.user_id, wid):
        values.append((path, hashlib.sha256(await w.read(wid, path)).hexdigest()))
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


class RepositoryService:
    def __init__(self, workspaces, connections=None, git_factory=ControlledGitService):
        self.w = workspaces
        self.owned = IntegrationOwnership(workspaces.session, workspaces.user_id)
        self.connections = connections or GitHubConnections(
            workspaces.session, workspaces.user_id, workspaces.secrets, workspaces.settings
        )
        self.git_factory = git_factory

    async def import_repository(self, ident):
        repo = await self.owned.repository(ident)
        repo, connection, service = await self.connections.verify_repository(repo)
        ident = str(uuid.uuid4())
        root = self.w.storage.create_workspace(self.w.user_id, ident)
        workspace = Workspace(
            id=ident,
            user_id=self.w.user_id,
            name=repo.full_name,
            type="REPOSITORY",
            source_type="GITHUB",
            source_filename=repo.full_name,
            root_path=root,
            status="CREATING",
        )
        self.w.session.add(workspace)
        await self.w.session.flush()
        try:
            git = self.git_factory(self.w, ident)
            sha = await git.clone_repository(repo.clone_url, repo.default_branch, service.token)
            link = RepositoryWorkspace(
                id=str(uuid.uuid4()),
                user_id=self.w.user_id,
                workspace_id=ident,
                github_repository_id=repo.id,
                connection_id=connection.id,
                default_branch=repo.default_branch,
                base_ref=repo.default_branch,
                base_commit_sha=sha,
                last_fetched_at=now(),
            )
            self.w.session.add(link)
            await self.w.index(ident)
            audit(self.w.session, self.w.user_id, "REPOSITORY_IMPORTED", "workspace", ident)
            return workspace
        except BaseException:
            self.w.storage.delete_workspace(self.w.user_id, ident)
            await self.w.session.delete(workspace)
            raise

    async def context(self, wid):
        link, repo, connection = await self.owned.repository_workspace(wid)
        return link, repo, connection, self.git_factory(self.w, wid)

    async def prepare(self, job):
        if job.mode == "READ_ONLY":
            return
        link, repo, connection, git = await self.context(job.workspace_id)
        _, _, service = await self.connections.verify_repository(repo)
        remote = await git.fetch(service.token)
        link.last_fetched_at = now()
        if remote != link.base_commit_sha:
            raise SafeError("STALE_REPOSITORY")
        if link.working_branch:
            if link.metadata_json.get("job_id") != job.id:
                raise SafeError("BRANCH_REQUIRES_REVIEW")
            if await git.current_branch() != link.working_branch:
                raise SafeError("WRONG_BRANCH")
        else:
            if await git.status() or await git.head() != link.base_commit_sha:
                raise SafeError("DIRTY_REPOSITORY")
            branch = agent_branch("task-" + job.id[:8])
            await git.create_branch(branch)
            link.working_branch = branch
            link.metadata_json = {"job_id": job.id}
            audit(
                self.w.session, self.w.user_id, "GIT_BRANCH_CREATED", "workspace", job.workspace_id
            )
        request = self.w.secrets.decrypt(job.request_text)
        match = re.search(r"(?i)issue\s*#?\s*(\d+)", request)
        if match and not link.metadata_json.get("issue_loaded"):
            value = await service.get_issue(repo.full_name, int(match.group(1)))
            context = ExternalToolOutputSanitizer(12000, [service.token]).context(
                {
                    "number": value["number"],
                    "title": value.get("title", ""),
                    "body": value.get("body", ""),
                },
                "GITHUB_ISSUE",
            )
            job.request_text = self.w.secrets.encrypt(
                (request + "\n" + json.dumps(context, ensure_ascii=False))[:16000]
            )
            link.metadata_json = {**link.metadata_json, "issue_loaded": True}
            audit(
                self.w.session, self.w.user_id, "GITHUB_ISSUE_READ", "workspace", job.workspace_id
            )
        await self.w.session.commit()

    async def writable(self, job):
        link, repo, connection, git = await self.context(job.workspace_id)
        if job.mode != "WORKSPACE" or not self.w.settings.github_write_enabled:
            raise SafeError("POLICY_DENIED")
        if (
            not link.working_branch
            or not link.working_branch.startswith("agent/")
            or link.working_branch in {"main", "master", repo.default_branch}
            or await git.current_branch() != link.working_branch
            or link.metadata_json.get("job_id") != job.id
        ):
            raise SafeError("PROTECTED_BRANCH")
        _, _, service = await self.connections.verify_repository(repo)
        if connection.connection_type == "PAT" and not repo.permissions_json.get("push"):
            raise SafeError("REPOSITORY_UNAUTHORIZED")
        for page in range(1, 11):
            branches = await service.list_branches(repo.full_name, page)
            if any(x.get("name") == link.working_branch and x.get("protected") for x in branches):
                raise SafeError("PROTECTED_BRANCH")
            if len(branches) < 100:
                break
        else:
            raise SafeError("TOO_MANY_REPOSITORIES")
        if await git.fetch(service.token) != link.base_commit_sha:
            raise SafeError("STALE_REPOSITORY")
        info = await git.get_remote_info()
        if info["url"] != repo.clone_url or info["remote"] != "origin":
            raise SafeError("UNSAFE_GIT_CONFIG")
        return link, repo, connection, git, service

    async def ready_to_commit(self, job, expected_files):
        link, repo, connection, git, service = await self.writable(job)
        changed = await git.get_changed_files()
        if set(changed) != set(expected_files) or not changed:
            raise SafeError("UNEXPECTED_FILES")
        if any(
            row["status"] in {"UU", "AA", "DD", "AU", "UA", "DU", "UD"}
            for row in await git.status()
        ):
            raise SafeError("GIT_CONFLICT")
        await RepositorySafetyScanner().enforce(self.w, job.workspace_id, changed)
        digest = await workspace_digest(self.w, job.workspace_id)
        if self.w.settings.git_require_validation:
            runs = list(
                await self.w.session.scalars(
                    select(ValidationRun)
                    .where(ValidationRun.job_id == job.id, ValidationRun.status == "PASSED")
                    .order_by(ValidationRun.created_at.desc())
                )
            )
            if not any(run.findings_json.get("workspace_digest") == digest for run in runs):
                raise SafeError("VALIDATION_REQUIRED")
        return link, repo, git, changed, digest

    async def commit(self, job, message, expected_files, *, approved=False):
        if not approved:
            raise SafeError("APPROVAL_REQUIRED")
        link, repo, git, changed, digest = await self.ready_to_commit(job, expected_files)
        await git.stage_paths(changed)
        staged = await git.staged_paths()
        if set(staged) != set(changed):
            raise SafeError("UNEXPECTED_FILES")
        sha = await git.commit(message)
        link.metadata_json = {
            **link.metadata_json,
            "committed_sha": sha,
            "committed_files": changed,
            "committed_digest": digest,
        }
        audit(self.w.session, self.w.user_id, "GIT_COMMIT_CREATED", "workspace", job.workspace_id)
        return {"sha": sha, "branch": link.working_branch, "files": changed}

    async def push(self, job, branch, expected_head, *, approved=False):
        if not approved:
            raise SafeError("APPROVAL_REQUIRED")
        link, repo, connection, git, service = await self.writable(job)
        if (
            branch != link.working_branch
            or expected_head != await git.head()
            or expected_head != link.metadata_json.get("committed_sha")
        ):
            raise SafeError("WRONG_REF")
        if not self.w.settings.github_push_ci_reviewed:
            raise SafeError("WORKFLOW_REVIEW_REQUIRED")
        if any(
            path.startswith(".github/workflows/")
            for path in link.metadata_json.get("committed_files", [])
        ):
            raise SafeError("WORKFLOW_WRITE_DENIED")
        if await git.status() or await workspace_digest(
            self.w, job.workspace_id
        ) != link.metadata_json.get("committed_digest"):
            raise SafeError("DIRTY_REPOSITORY")
        await RepositorySafetyScanner().enforce(
            self.w, job.workspace_id, link.metadata_json["committed_files"]
        )
        # A Git push triggers repository-configured workflows. No workflow/deployment API is invoked.
        await git.push_branch(branch, service.token)
        link.metadata_json = {**link.metadata_json, "pushed_sha": expected_head}
        audit(self.w.session, self.w.user_id, "GIT_BRANCH_PUSHED", "workspace", job.workspace_id)
        return {"repository": repo.full_name, "branch": branch, "sha": expected_head}

    async def pr_body(self, job, summary):
        link, _, _, _ = await self.context(job.workspace_id)
        runs = list(
            await self.w.session.scalars(
                select(ValidationRun)
                .where(ValidationRun.job_id == job.id)
                .order_by(ValidationRun.created_at.desc())
                .limit(5)
            )
        )
        files = link.metadata_json.get("committed_files", [])
        validation = "\n".join("- " + run.status for run in runs) or "- NOT_RUN"
        return (
            "## Summary\n"
            + summary[:12000]
            + "\n\n## Changes\n"
            + "\n".join("- `" + path.replace("`", "") + "`" for path in files)
            + "\n\n## Validation\n"
            + validation
            + "\n\n## Risks / Notes\n- Agent branch; human review required. No automatic merge or deployment."
        )

    async def create_pr(self, job, data, *, approved=False):
        if not approved:
            raise SafeError("APPROVAL_REQUIRED")
        link, repo, connection, git, service = await self.writable(job)
        sha = await git.head()
        if (
            link.metadata_json.get("pushed_sha") != sha
            or link.metadata_json.get("committed_sha") != sha
        ):
            raise SafeError("PUSH_REQUIRED")
        result = await service.create_pull_request(
            repo.full_name, link.working_branch, repo.default_branch, data
        )
        audit(self.w.session, self.w.user_id, "PULL_REQUEST_CREATED", "workspace", job.workspace_id)
        return {"number": result["number"], "url": result["html_url"]}

    async def read_github(self, job, operation, args):
        link, repo, connection, git = await self.context(job.workspace_id)
        _, _, service = await self.connections.verify_repository(repo)
        method = {
            "github.get_issue": service.get_issue,
            "github.get_pull_request": service.get_pull_request,
            "github.list_pull_requests": service.list_pull_requests,
            "github.compare_refs": service.compare_refs,
            "github.checks": service.checks,
            "github.actions": service.actions,
            "github.statuses": service.statuses,
        }[operation]
        result = await method(repo.full_name, **args)
        label = (
            "GITHUB_ISSUE"
            if "issue" in operation
            else "GITHUB_PR"
            if "pull" in operation
            else "TOOL_RESULT"
        )
        audit(
            self.w.session,
            self.w.user_id,
            "GITHUB_ISSUE_READ" if label == "GITHUB_ISSUE" else "GITHUB_PR_READ",
            "workspace",
            job.workspace_id,
        )
        return ExternalToolOutputSanitizer(24000, [service.token]).context(result, label)
