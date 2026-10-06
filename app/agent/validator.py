import ast
import hashlib
import uuid

from sqlalchemy import select

from app.core.exceptions import SafeError
from app.db.models.agent import ValidationRun, WorkspaceChangeSet
from app.sandbox.commands import ValidationCommandDetector
from app.sandbox.runner import runner_for
from app.services.audit_service import audit


class AgentValidator:
    def __init__(self, workspaces, job, runner=None):
        self.workspaces, self.job = workspaces, job
        self.runner = runner or runner_for(workspaces.settings)

    async def syntax(self, paths):
        findings = []
        for path in paths:
            if not path.endswith(".py"):
                continue
            try:
                data = await self.workspaces.read(self.job.workspace_id, path)
                ast.parse(data)
                findings.append({"path": path, "check": "python_syntax", "passed": True})
            except SyntaxError as error:
                findings.append(
                    {"path": path, "check": "python_syntax", "passed": False, "line": error.lineno}
                )
            except SafeError:
                findings.append(
                    {
                        "path": path,
                        "check": "python_syntax",
                        "passed": False,
                        "error_code": "NOT_FOUND",
                    }
                )
        return {"passed": all(item["passed"] for item in findings), "findings": findings}

    async def validate(self):
        files = await self.workspaces.files(self.job.workspace_id)
        actual = set(
            self.workspaces.storage.list_files(self.workspaces.user_id, self.job.workspace_id)
        )
        expected = {f.relative_path for f in files}
        changes = await self.workspaces.session.scalars(
            select(WorkspaceChangeSet).where(
                WorkspaceChangeSet.job_id == self.job.id, WorkspaceChangeSet.status == "APPLIED"
            )
        )
        paths = set()
        for change in changes:
            paths.update(
                set(change.summary_json["files"]) - set(change.summary_json["deleted_files"])
            )
        syntax = await self.syntax(sorted(paths))
        mismatches = []
        for file in files:
            current = await self.workspaces.read(self.job.workspace_id, file.relative_path)
            if hashlib.sha256(current).hexdigest() != file.sha256:
                mismatches.append(file.relative_path)
        runs = list(
            await self.workspaces.session.scalars(
                select(ValidationRun).where(ValidationRun.job_id == self.job.id)
            )
        )
        return {
            "validation_runs": [
                {"command_id": run.command_id, "status": run.status} for run in runs
            ],
            "tests": "RUN" if runs else "NOT_RUN",
            "passed": syntax["passed"] and actual == expected and not mismatches,
            "syntax": syntax,
            "unexpected_files": sorted(actual ^ expected),
            "hash_mismatches": mismatches,
            "goal_comparison": "REVIEW_REQUIRED",
        }

    async def run(self, command_id, cancelled):
        commands = ValidationCommandDetector().resolve(
            command_id, await self.workspaces.manifest(self.job.workspace_id)
        )
        session = self.workspaces.session
        value = ValidationRun(
            id=str(uuid.uuid4()),
            job_id=self.job.id,
            workspace_id=self.job.workspace_id,
            command_id=command_id,
            command_json=commands,
            status="RUNNING",
        )
        session.add(value)
        audit(session, self.workspaces.user_id, "VALIDATION_STARTED", "validation", value.id)
        await session.commit()
        try:
            result = await self.runner.run(self.workspaces, self.job, command_id, cancelled)
            value.exit_code, value.duration_ms, value.output_truncated = (
                result.exit_code,
                result.duration_ms,
                result.truncated,
            )
            value.output_encrypted = self.workspaces.secrets.encrypt(result.output)
            value.status = (
                result.status
                if result.status != "COMPLETED"
                else ("PASSED" if result.exit_code == 0 else "FAILED")
            )
            self.job.validation_runtime_ms += result.duration_ms
            value.findings_json = {
                "network": "DISABLED",
                "isolated_copy": True,
                "passed": value.status == "PASSED",
            }
            audit(
                session,
                self.workspaces.user_id,
                "VALIDATION_FINISHED",
                "validation",
                value.id,
                status=value.status,
            )
            await session.commit()
            return {
                "validation_id": value.id,
                "status": value.status,
                "exit_code": result.exit_code,
                "duration_ms": result.duration_ms,
                "truncated": result.truncated,
                "output": result.output,
            }
        except SafeError as error:
            value.status = "FAILED"
            value.findings_json = {"error_code": error.code}
            audit(
                session,
                self.workspaces.user_id,
                "VALIDATION_FINISHED",
                "validation",
                value.id,
                status="FAILED",
            )
            await session.commit()
            raise
