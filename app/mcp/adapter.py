import json
import re
from types import SimpleNamespace

from app.core.exceptions import SafeError
from app.mcp.policy import validate_arguments


class MCPInputSchema:
    def __init__(self, schema):
        self.schema = schema

    def model_json_schema(self):
        return self.schema

    def model_validate(self, arguments):
        validate_arguments(self.schema, arguments)
        return SimpleNamespace(model_dump=lambda: dict(arguments))


def tool_namespace(tool):
    integration = (
        re.sub(r"[^a-z0-9_]", "_", tool.metadata_json.get("integration", "generic").lower())[:24]
        or "generic"
    )
    name = re.sub(r"[^a-zA-Z0-9_]", "_", tool.external_name)[:64] or "tool"
    return "mcp." + integration + "." + name + "_" + tool.id.replace("-", "")


class MCPToolAdapter:
    def __init__(self, service, tool, server):
        self.service, self.tool, self.server = service, tool, server

    def approval_arguments(self, arguments):
        return {
            "server_id": self.server.id,
            "tool_id": self.tool.id,
            "schema_fingerprint": self.tool.metadata_json["fingerprint"],
            "arguments": arguments,
        }

    async def policy(self, job, args):
        current = await self.service.owned.tool(self.tool.id)
        server = await self.service.owned.server(current.mcp_server_id)
        self.service.reviewed_rating(server, current)
        await self.service.require_scopes(current, server)
        self.service.policy.enforce(current, args, job.mode)
        return (
            current.requires_approval,
            current.risk_level,
            self.approval_arguments(args),
            {
                "server_id": server.id,
                "server": server.name,
                "tool_id": current.id,
                "tool": current.external_name,
                "arguments": json.loads(self.service.sanitizer().clean(args)),
            },
        )

    async def execute(self, job, args, approved):
        required, _, _, _ = await self.policy(job, args)
        if required and not approved:
            raise SafeError("APPROVAL_REQUIRED")
        return await self.service.call(self.tool, args, job.mode, approved)
