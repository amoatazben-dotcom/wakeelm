import asyncio
import hashlib
import json
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from app.agent.approvals import ApprovalService
from app.agent.ownership import AgentOwnership
from app.agent.patches import PatchEngine
from app.agent.schemas import (
    ChangeSetInput,
    EmptyInput,
    FileInput,
    ProposePatchInput,
    ReadInput,
    RequestApprovalInput,
    Risk,
    SearchInput,
    ToolOutput,
    ToolRequest,
    ValidationInput,
)
from app.agent.validator import AgentValidator
from app.core.exceptions import SafeError
from app.db.base import now
from app.db.models.agent import ToolCall
from app.sandbox.commands import ValidationCommandDetector
from app.services.audit_service import audit
from app.services.search_service import SearchService


@dataclass(frozen=True)
class ToolSpec:
    name: str
    schema: type[BaseModel]
    description: str
    risk: Risk = Risk.LOW
    modes: tuple = ("READ_ONLY", "SUGGEST", "WORKSPACE")
    timeout: int = 30
    output_limit: int = 24000
    output_schema: type[BaseModel] = ToolOutput


SPECS = [
    ToolSpec("workspace.list_files", EmptyInput, "List project relative paths and content hashes."),
    ToolSpec("workspace.read_file", ReadInput, "Read a bounded line range from a project file."),
    ToolSpec("workspace.file_info", FileInput, "Get file size and current SHA256."),
    ToolSpec("project.search_text", SearchInput, "Literal project text search."),
    ToolSpec("project.search_files", SearchInput, "Search relative filenames."),
    ToolSpec("project.search_symbols", SearchInput, "Search indexed Python symbols."),
    ToolSpec("project.get_manifest", EmptyInput, "Get detected project architecture."),
    ToolSpec(
        "workspace.propose_patch",
        ProposePatchInput,
        "Propose exact hash-bound edits without applying them.",
        Risk.MEDIUM,
        ("SUGGEST", "WORKSPACE"),
    ),
    ToolSpec(
        "workspace.apply_patch",
        ChangeSetInput,
        "Apply a previously proposed hash-bound patch.",
        Risk.MEDIUM,
        ("WORKSPACE",),
    ),
    ToolSpec(
        "workspace.restore_file",
        ChangeSetInput,
        "Restore the complete change set from encrypted snapshots.",
        Risk.HIGH,
        ("WORKSPACE",),
    ),
    ToolSpec("project.diff", ChangeSetInput, "Read a proposed or applied diff."),
    ToolSpec("validation.detect_commands", EmptyInput, "List available fixed command IDs."),
    ToolSpec(
        "validation.run",
        ValidationInput,
        "Run one detected command ID in an isolated container after approval.",
        Risk.HIGH,
        ("WORKSPACE",),
        310,
    ),
    ToolSpec(
        "agent.request_approval",
        RequestApprovalInput,
        "Request approval for a known action; cannot grant approval.",
        Risk.MEDIUM,
        ("WORKSPACE",),
    ),
]


class ApprovalPending(Exception):
    pass


def redact(arguments):
    return {
        key: value
        for key, value in arguments.items()
        if key in {"path", "start_line", "end_line", "change_set_id", "command_id", "max_results"}
    }


class ToolRegistry:
    def __init__(self, workspaces, job, cancelled, runner=None):
        self.workspaces, self.job, self.cancelled = workspaces, job, cancelled
        self.specs = {spec.name: spec for spec in SPECS}
        self.patches = PatchEngine(workspaces, job)
        self.validator = AgentValidator(workspaces, job, runner)
        self.approvals = ApprovalService(
            workspaces.session, workspaces.user_id, workspaces.settings
        )

    def schemas(self):
        return [
            {
                "type": "function",
                "function": {
                    "name": spec.name.replace(".", "__"),
                    "description": spec.description,
                    "parameters": spec.schema.model_json_schema(),
                },
            }
            for spec in SPECS
            if self.job.mode in spec.modes
        ]

    def normalize(self, request, resolve=True):
        spec = self.specs.get(request.tool_name)
        if spec is None or self.job.mode not in spec.modes:
            raise SafeError("POLICY_DENIED")
        args = dict(request.arguments)
        if resolve and args.get("change_set_id") == "$last_patch":
            args["change_set_id"] = self.job.result_json.get("last_patch", "")
        try:
            args = spec.schema.model_validate(args).model_dump()
        except (ValidationError, ValueError):
            raise SafeError("INVALID_TOOL_ARGUMENTS") from None
        if (
            isinstance(spec.schema, type)
            and spec.schema is ReadInput
            and args["end_line"] < args["start_line"]
        ):
            raise SafeError("INVALID_TOOL_ARGUMENTS")
        return spec, args

    async def policy(self, spec, args):
        required = spec.name in {
            "validation.run",
            "workspace.restore_file",
            "agent.request_approval",
        }
        risk = spec.risk
        summary = redact(args)
        if spec.name == "workspace.apply_patch":
            value = await self.patches.proposal(args["change_set_id"])
            required = (
                value.summary_json["risk"] == "HIGH"
                or self.workspaces.settings.require_edit_approval
            )
            risk = Risk(value.summary_json["risk"])
            summary = {**summary, **value.summary_json}
        if spec.name == "agent.request_approval":
            target = self.specs.get(args["tool_name"])
            if not target or target.name == spec.name or self.job.mode not in target.modes:
                raise SafeError("POLICY_DENIED")
            target, target_args = self.normalize(
                ToolRequest(tool_name=args["tool_name"], arguments=args["arguments"])
            )
            args["arguments"] = target_args
            risk = target.risk
            summary = {"tool_name": target.name, "arguments": redact(target_args)}
            if target.name == "workspace.apply_patch":
                value = await self.patches.proposal(target_args["change_set_id"])
                summary.update(value.summary_json)
                risk = Risk(value.summary_json["risk"])
            if target.name == "validation.run":
                summary["argv"] = ValidationCommandDetector().resolve(
                    target_args["command_id"], await self.workspaces.manifest(self.job.workspace_id)
                )
                summary["network"] = "DISABLED"

        if spec.name == "validation.run":
            summary["argv"] = ValidationCommandDetector().resolve(
                args["command_id"], await self.workspaces.manifest(self.job.workspace_id)
            )
            summary["network"] = "DISABLED"
        approved = await self.approvals.approved(self.job, spec.name, args)
        if required and not approved:
            await self.approvals.request(self.job, spec.name, args, risk, summary)
            await self.workspaces.session.commit()
            raise ApprovalPending()
        return approved

    async def execute(self, request):
        await AgentOwnership(self.workspaces.session, self.workspaces.user_id).job(self.job.id)
        if await self.cancelled():
            raise SafeError("JOB_CANCELLED")
        try:
            spec, args = self.normalize(request)
            approved = await self.policy(spec, args)
        except SafeError as error:
            audit(
                self.workspaces.session,
                self.workspaces.user_id,
                "TOOL_DENIED",
                "agent_job",
                self.job.id,
                status=error.code,
            )
            await self.workspaces.session.commit()
            raise
        if self.job.tool_calls_count >= self.workspaces.settings.max_tool_calls:
            raise SafeError("AGENT_LIMIT")
        log = ToolCall(
            job_id=self.job.id,
            tool_name=spec.name,
            risk_level=spec.risk,
            status="RUNNING",
            input_summary=redact(args),
        )
        self.workspaces.session.add(log)
        self.job.tool_calls_count += 1
        await self.workspaces.session.commit()
        try:
            async with asyncio.timeout(spec.timeout):
                result = await self._dispatch(spec.name, args, approved)
            result = spec.output_schema.model_validate(
                {"data": result, "summary": "TOOL_COMPLETED"}
            ).data
            log.status = "COMPLETED"
            log.output_summary = {"status": "OK"}
            serialized = json.dumps(result, ensure_ascii=False)
            if len(serialized.encode()) > spec.output_limit:
                preserved = {
                    key: value
                    for key, value in result.items()
                    if key
                    in {"change_set_id", "validation_id", "status", "exit_code", "duration_ms"}
                }
                result = {
                    **preserved,
                    "truncated": True,
                    "preview": serialized.encode()[: spec.output_limit].decode(
                        "utf-8", errors="ignore"
                    ),
                }
            return result
        except SafeError as error:
            log.status = "FAILED"
            log.output_summary = {"error_code": error.code}
            raise
        except TimeoutError:
            log.status = "FAILED"
            raise SafeError("TOOL_TIMEOUT") from None
        finally:
            audit(
                self.workspaces.session,
                self.workspaces.user_id,
                "TOOL_EXECUTED",
                "agent_job",
                self.job.id,
                status=log.status,
            )
            log.completed_at = now()
            await self.workspaces.session.commit()

    async def _dispatch(self, name, args, approved):
        wid = self.job.workspace_id
        w = self.workspaces
        if name == "agent.request_approval":
            target, target_args = self.normalize(
                ToolRequest(tool_name=args["tool_name"], arguments=args["arguments"])
            )
            return await self._dispatch(target.name, target_args, approved)
        if name == "workspace.list_files":
            return {
                "files": [
                    {"path": f.relative_path, "sha256": f.sha256, "binary": f.is_binary}
                    for f in await w.files(wid)
                ]
            }
        if name in {"workspace.read_file", "workspace.file_info"}:
            raw = await w.read(wid, args["path"])
            info = {
                "path": args["path"],
                "sha256": hashlib.sha256(raw).hexdigest(),
                "size_bytes": len(raw),
            }
            if name == "workspace.read_file":
                parsed = w.parsers.parse(args["path"], raw)
                if parsed.text is None:
                    raise SafeError("BINARY_FILE")
                lines = parsed.text.splitlines()
                start = args["start_line"]
                end = min(args["end_line"], start + 399)
                text = "\n".join(lines[start - 1 : end])
                info.update(
                    text=text[:24000],
                    start_line=start,
                    end_line=min(end, len(lines)),
                    truncated=len(text) > 24000 or args["end_line"] > end,
                )
            return info
        if name.startswith("project.search_"):
            search = SearchService(w)
            kind = name.removeprefix("project.search_")
            method = {"text": search.text, "files": search.files, "symbols": search.symbols}[kind]
            kwargs = {"max_results": args["max_results"]}
            if kind == "text":
                kwargs["glob"] = args["glob"]
            return {"matches": await method(wid, args["query"], **kwargs)}
        if name == "project.get_manifest":
            return await w.manifest(wid)
        if name == "workspace.propose_patch":
            return await self.patches.propose(args)
        if name == "workspace.apply_patch":
            return await self.patches.apply(args["change_set_id"], approved)
        if name == "workspace.restore_file":
            return await self.patches.rollback(args["change_set_id"])
        if name == "project.diff":
            return await self.patches.diff(args["change_set_id"])
        if name == "validation.detect_commands":
            return {"commands": ValidationCommandDetector().detect(await w.manifest(wid))}
        if name == "validation.run":
            return await self.validator.run(args["command_id"], self.cancelled)
        raise SafeError("POLICY_DENIED")
