import asyncio
import json
import uuid

from sqlalchemy import select

from app.core.exceptions import SafeError
from app.db.base import now
from app.db.models.agent import AgentJob
from app.db.models.projects import Workspace
from app.services.audit_service import audit

OPERATIONS = {
    "GITHUB_VERIFY_PAT",
    "GITHUB_SYNC",
    "REPOSITORY_IMPORT",
    "MCP_DISCOVER",
    "MCP_RESOURCE",
    "MCP_PROMPT",
}


class IntegrationJobs:
    def __init__(self, workspaces):
        self.w = workspaces

    async def control_workspace(self):
        from app.db.models import User

        # User row serializes creation of the hidden integration workspace.
        await self.w.session.scalar(select(User).where(User.id == self.w.user_id).with_for_update())
        value = await self.w.session.scalar(
            select(Workspace).where(
                Workspace.user_id == self.w.user_id,
                Workspace.type == "INTEGRATION_CONTROL",
                Workspace.status != "DELETED",
            )
        )
        if value:
            return value
        ident = str(uuid.uuid4())
        root = self.w.storage.create_workspace(self.w.user_id, ident)
        value = Workspace(
            id=ident,
            user_id=self.w.user_id,
            name="Integrations",
            type="INTEGRATION_CONTROL",
            source_type="INTERNAL",
            source_filename="integrations",
            root_path=root,
            status="READY",
        )
        self.w.session.add(value)
        await self.w.session.flush()
        await self.w.index(ident)
        return value

    async def enqueue(self, operation, payload, workspace_id=None, chat_id=None):
        if operation not in OPERATIONS:
            raise SafeError("POLICY_DENIED")
        if not getattr(self.w.settings, "integration_jobs_enabled", True):
            raise SafeError("INTEGRATIONS_DISABLED")
        workspace = (
            await self.w.owned(workspace_id) if workspace_id else await self.control_workspace()
        )
        value = AgentJob(
            id=str(uuid.uuid4()),
            user_id=self.w.user_id,
            workspace_id=workspace.id,
            kind=operation,
            mode="READ_ONLY",
            request_text=self.w.secrets.encrypt(operation),
            payload_encrypted=self.w.secrets.encrypt(json.dumps(payload)),
            max_steps=1,
            status="QUEUED",
            telegram_chat_id=chat_id,
        )
        self.w.session.add(value)
        await self.w.session.flush()
        return value


class IntegrationJobExecutor:
    def __init__(self, workspaces, notify=None):
        self.w, self.notify = workspaces, notify

    async def run(self, job):
        from app.github.connections import GitHubConnections
        from app.github.repositories import RepositoryService
        from app.mcp.service import MCPService

        if job.kind not in OPERATIONS:
            raise SafeError("POLICY_DENIED")
        try:
            async with self.w.limits.lock(
                "agent:workspace:" + job.workspace_id, self.w.settings.max_task_duration + 60
            ):
                if await self.w.limits.redis.get("agent:cancel:" + job.id):
                    raise SafeError("JOB_CANCELLED")
                job.status = "RUNNING"
                job.started_at = now()
                await self.w.session.commit()
                payload = json.loads(self.w.secrets.decrypt(job.payload_encrypted))
                github = GitHubConnections(
                    self.w.session, self.w.user_id, self.w.secrets, self.w.settings
                )
                mcp = MCPService(
                    self.w.session, self.w.user_id, self.w.settings, self.w.secrets, self.w.limits
                )
                async with asyncio.timeout(self.w.settings.max_task_duration):
                    if job.kind == "GITHUB_VERIFY_PAT":
                        value = await github.create_pat(payload["token"])
                        job.result_json = {"connection_id": value.id}
                        await github.sync(value.id)
                    elif job.kind == "GITHUB_SYNC":
                        await github.sync(payload["connection_id"])
                    elif job.kind == "REPOSITORY_IMPORT":
                        value = await RepositoryService(self.w, github).import_repository(
                            payload["repository_id"]
                        )
                        job.result_json = {"workspace_id": value.id}
                    elif job.kind == "MCP_DISCOVER":
                        await mcp.discover(payload["server_id"])
                        job.result_json = {"server_id": payload["server_id"]}
                    elif job.kind == "MCP_RESOURCE":
                        value = await mcp.read_resource(payload["server_id"], payload["uri"])
                        job.result_json = {
                            "output_encrypted": self.w.secrets.encrypt(json.dumps(value))
                        }
                    elif job.kind == "MCP_PROMPT":
                        value = await mcp.prompt(
                            payload["server_id"], payload["name"], payload.get("arguments", {})
                        )
                        job.result_json = {
                            "output_encrypted": self.w.secrets.encrypt(json.dumps(value))
                        }
                if await self.w.limits.redis.get("agent:cancel:" + job.id):
                    raise SafeError("JOB_CANCELLED")
                job.status = "COMPLETED"
                job.current_step = 1
        except asyncio.CancelledError:
            job.status = "FAILED"
            job.failure_code = "WORKER_INTERRUPTED"
            raise
        except SafeError as error:
            job.status = "CANCELLED" if error.code == "JOB_CANCELLED" else "FAILED"
            job.failure_code = error.code
        except TimeoutError:
            job.status = "LIMIT_REACHED"
            job.failure_code = "TIMEOUT"
        except Exception:
            job.status = "FAILED"
            job.failure_code = "INTERNAL"
        finally:
            job.completed_at = now()
            job.payload_encrypted = None  # verified tokens never remain in historical job payloads
            audit(
                self.w.session,
                self.w.user_id,
                "INTEGRATION_JOB_FINISHED",
                "agent_job",
                job.id,
                status=job.status,
            )
            await self.w.session.commit()
            if self.notify:
                await self.notify(job)
        return job
