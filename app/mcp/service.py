import json
import uuid

from sqlalchemy import delete, select

from app.core.exceptions import SafeError
from app.db.base import now
from app.db.models.integrations import MCPCredential, MCPResource, MCPServer, MCPTool
from app.integrations.http import validate_https
from app.integrations.oauth import MCPOAuth
from app.integrations.ownership import IntegrationOwnership
from app.integrations.sanitizer import ExternalToolOutputSanitizer
from app.mcp.client import MCPClient
from app.mcp.policy import MCPRiskPolicy, check_schema, fingerprint
from app.services.audit_service import audit


class MCPService:
    def __init__(self, session, user_id, settings, secrets, limits, client=None, http=None):
        self.session, self.user_id, self.settings, self.secrets, self.limits = (
            session,
            user_id,
            settings,
            secrets,
            limits,
        )
        self.client = client or MCPClient(settings)
        self.owned = IntegrationOwnership(session, user_id)
        self.oauth = MCPOAuth(session, user_id, settings, secrets, limits, http)
        self.policy = MCPRiskPolicy(settings)

    async def add(self, name, url, transport="streamable_http", token=None):
        if transport != "streamable_http" or transport not in self.settings.mcp_allowed_transports:
            raise SafeError("TRANSPORT_DENIED")
        if not name.strip() or len(name) > 100:
            raise SafeError("INVALID_INPUT")
        await validate_https(url)
        from urllib.parse import urlsplit

        if urlsplit(url).query or self.sanitizer().clean(url) != url:
            raise SafeError("INVALID_URL")
        value = MCPServer(
            id=str(uuid.uuid4()),
            user_id=self.user_id,
            name=name,
            server_url=url,
            transport=transport,
            status="PENDING",
            auth_type="TOKEN" if token else "NONE",
            encrypted_auth_config=self.secrets.encrypt(json.dumps({"token": token}))
            if token
            else None,
        )
        self.session.add(value)
        await self.session.flush()
        audit(self.session, self.user_id, "MCP_SERVER_ADDED", "mcp_server", value.id)
        return value

    async def configure_token(self, ident, token):
        server = await self.owned.server(ident, False)
        if (
            not isinstance(token, str)
            or not 4 <= len(token) <= 10000
            or any(ord(c) < 33 for c in token)
        ):
            raise SafeError("INVALID_CREDENTIAL")
        await self.session.execute(
            delete(MCPCredential).where(
                MCPCredential.mcp_server_id == ident, MCPCredential.user_id == self.user_id
            )
        )
        server.encrypted_auth_config = self.secrets.encrypt(json.dumps({"token": token}))
        server.auth_type, server.status = "TOKEN", "PENDING"
        audit(self.session, self.user_id, "MCP_SERVER_AUTH_COMPLETED", "mcp_server", ident)
        return server

    async def token(self, server):
        if server.auth_type == "OAUTH":
            return await self.oauth.credential(server)
        if server.auth_type == "TOKEN":
            return json.loads(self.secrets.decrypt(server.encrypted_auth_config))["token"]
        return None

    def sanitizer(self, token=None):
        values = [token]
        for name in (
            "telegram_bot_token",
            "master_encryption_key",
            "database_url",
            "redis_url",
            "github_app_private_key",
            "github_client_secret",
            "github_webhook_secret",
        ):
            value = getattr(self.settings, name, None)
            if value and hasattr(value, "get_secret_value"):
                values.append(value.get_secret_value())
        return ExternalToolOutputSanitizer(self.settings.mcp_max_response_bytes, values)

    async def discover(self, ident):
        server = await self.owned.server(ident, False)
        if server.status == "DISABLED":
            raise SafeError("NOT_FOUND")
        token = await self.token(server)
        try:
            result = await self.client.discover(server.server_url, token)
        except SafeError as error:
            server.status = "AUTH_REQUIRED" if error.code == "AUTH_REQUIRED" else "OFFLINE"
            await self.session.commit()
            raise
        clean = self.sanitizer(token)
        server.protocol_version = result["protocol_version"]
        server.server_info_json = json.loads(clean.clean(result["server_info"]))
        server.capabilities_json = {
            **result["capabilities"],
            "prompts": json.loads(clean.clean(result["prompts"])),
            "resource_templates": json.loads(clean.clean(result.get("resource_templates", []))),
        }
        server.last_connected_at = server.last_discovered_at = now()
        server.status = "CONNECTED"
        known = {
            x.external_name: x
            for x in await self.session.scalars(
                select(MCPTool).where(MCPTool.mcp_server_id == ident)
            )
        }
        names = set()
        for data in result["tools"]:
            name = data["name"]
            if not isinstance(name, str) or not name or len(name) > 255:
                raise SafeError("INVALID_RESPONSE")
            names.add(name)
            value = known.get(name)
            identity = fingerprint(
                {
                    "schema": data["inputSchema"],
                    "description": data.get("description", ""),
                    "output": data.get("outputSchema"),
                }
            )
            changed = value and value.metadata_json.get("fingerprint") != identity
            if value is None:
                value = MCPTool(id=str(uuid.uuid4()), mcp_server_id=ident, external_name=name)
                self.session.add(value)
            schema = data["inputSchema"]
            rating = self.policy.classify(server, data)
            try:
                check_schema(schema)
            except SafeError:
                rating = {
                    "risk": "CRITICAL",
                    "reviewed": False,
                    "approval": True,
                    "capability": "INVALID_SCHEMA",
                }
            if data.get("outputSchema"):
                try:
                    check_schema(data["outputSchema"])
                except SafeError:
                    rating = {
                        "risk": "CRITICAL",
                        "reviewed": False,
                        "approval": True,
                        "capability": "INVALID_SCHEMA",
                    }
            value.display_name = name[:100]
            value.description = clean.clean(data.get("description", ""))[:4000]
            cleaned_schema = json.loads(clean.clean(schema))
            cleaned_output = json.loads(clean.clean(data.get("outputSchema")))
            if cleaned_schema != schema or cleaned_output != data.get("outputSchema"):
                rating = {
                    "risk": "CRITICAL",
                    "reviewed": False,
                    "approval": True,
                    "capability": "SECRET_SCHEMA",
                }
            value.input_schema_json = cleaned_schema
            value.output_schema_json = cleaned_output
            value.risk_level = rating["risk"]
            value.requires_approval = rating["approval"]
            value.is_enabled = bool(value.is_enabled and rating["reviewed"] and not changed)
            value.metadata_json = {
                **rating,
                "fingerprint": identity,
                "needs_review": bool(changed or not rating["reviewed"]),
            }
            value.last_seen_at = now()
        for name, value in known.items():
            if name not in names:
                value.is_enabled = False
                value.metadata_json = {**value.metadata_json, "missing": True}
        await self.session.execute(delete(MCPResource).where(MCPResource.mcp_server_id == ident))
        for data in result["resources"]:
            if clean.clean(data["uri"]) != data["uri"]:
                continue  # Never expose a resource identifier containing recognizable credentials.
            self.session.add(
                MCPResource(
                    id=str(uuid.uuid4()),
                    mcp_server_id=ident,
                    uri=data["uri"],
                    name=clean.clean(data.get("name", ""))[:255],
                    description=clean.clean(data.get("description", ""))[:4000],
                    mime_type=data.get("mimeType"),
                )
            )
        audit(
            self.session,
            self.user_id,
            "MCP_CAPABILITIES_DISCOVERED",
            "mcp_server",
            ident,
            count=len(names),
        )
        audit(self.session, self.user_id, "MCP_SERVER_CONNECTED", "mcp_server", ident)
        await self.session.flush()
        return server

    async def list(self):
        return list(
            await self.session.scalars(
                select(MCPServer).where(
                    MCPServer.user_id == self.user_id, MCPServer.status != "REMOVED"
                )
            )
        )

    async def tools(self, ident):
        await self.owned.server(ident, False)
        return list(
            await self.session.scalars(select(MCPTool).where(MCPTool.mcp_server_id == ident))
        )

    async def resources(self, ident):
        await self.owned.server(ident, False)
        return list(
            await self.session.scalars(
                select(MCPResource).where(MCPResource.mcp_server_id == ident)
            )
        )

    async def enable(self, ident, enabled=True):
        value = await self.session.scalar(
            select(MCPTool)
            .join(MCPServer)
            .where(
                MCPTool.id == ident,
                MCPServer.user_id == self.user_id,
                MCPServer.status == "CONNECTED",
            )
        )
        if not value:
            raise SafeError("NOT_FOUND")
        server = await self.owned.server(value.mcp_server_id)
        rating = self.policy.classify(
            server,
            {
                "name": value.external_name,
                "description": value.description,
                "inputSchema": value.input_schema_json,
                "outputSchema": value.output_schema_json,
            },
        )
        if enabled and (not rating["reviewed"] or rating["risk"] == "CRITICAL"):
            raise SafeError("MCP_REVIEW_REQUIRED")
        value.is_enabled = enabled
        value.metadata_json = {**value.metadata_json, **rating, "needs_review": False}
        value.risk_level = rating["risk"]
        value.requires_approval = rating["approval"]
        audit(
            self.session,
            self.user_id,
            "MCP_TOOL_ENABLED" if enabled else "MCP_TOOL_DISABLED",
            "mcp_tool",
            ident,
        )
        return value

    async def remove(self, ident):
        server = await self.owned.server(ident, False)
        tools = await self.tools(ident)
        server.status = "REMOVED"
        server.encrypted_auth_config = None
        await self.session.execute(
            delete(MCPCredential).where(MCPCredential.mcp_server_id == ident)
        )
        for value in tools:
            value.is_enabled = False
        audit(self.session, self.user_id, "MCP_SERVER_REMOVED", "mcp_server", ident)

    async def disable(self, ident):
        server = await self.owned.server(ident, False)
        server.status = "DISABLED"
        for tool in await self.tools(ident):
            tool.is_enabled = False
        audit(self.session, self.user_id, "MCP_SERVER_DISABLED", "mcp_server", ident)

    def reviewed_rating(self, server, tool):
        rating = self.policy.classify(
            server,
            {
                "name": tool.external_name,
                "description": tool.description,
                "inputSchema": tool.input_schema_json,
                "outputSchema": tool.output_schema_json,
            },
        )
        keys = ("risk", "capability", "approval", "required_scopes", "integration", "fingerprint")
        if not rating["reviewed"] or any(rating.get(k) != tool.metadata_json.get(k) for k in keys):
            raise SafeError("MCP_REVIEW_REQUIRED")
        return rating

    async def require_scopes(self, tool, server):
        required = set(tool.metadata_json.get("required_scopes", []))
        if required:
            cred = await self.session.scalar(
                select(MCPCredential).where(
                    MCPCredential.user_id == self.user_id, MCPCredential.mcp_server_id == server.id
                )
            )
            if (
                not cred
                or cred.issuer not in self.settings.mcp_oauth_clients
                or not required <= set(cred.scopes_json)
            ):
                raise SafeError("SCOPE_REQUIRED")

    async def call(self, tool, args, mode, approved=False):
        tool = await self.owned.tool(tool.id)
        server = await self.owned.server(tool.mcp_server_id)
        self.reviewed_rating(server, tool)
        self.policy.enforce(tool, args, mode)
        if tool.requires_approval and not approved:
            raise SafeError("APPROVAL_REQUIRED")
        token = await self.token(server)
        await self.require_scopes(tool, server)
        audit(self.session, self.user_id, "MCP_TOOL_CALL_REQUESTED", "mcp_tool", tool.id)
        result = await self.client.call(server.server_url, tool.external_name, args, token)
        if tool.output_schema_json and result.get("structuredContent") is not None:
            from app.mcp.policy import validate_arguments

            validate_arguments(tool.output_schema_json, result["structuredContent"])
        audit(self.session, self.user_id, "MCP_TOOL_CALL_EXECUTED", "mcp_tool", tool.id)
        return self.sanitizer(token).context(result, "TOOL_RESULT")

    async def read_resource(self, ident, uri):
        server = await self.owned.server(ident)
        resources = await self.resources(ident)
        if uri not in {r.uri for r in resources}:
            raise SafeError("NOT_FOUND")
        token = await self.token(server)
        result = await self.client.read_resource(server.server_url, uri, token)
        audit(self.session, self.user_id, "MCP_RESOURCE_READ", "mcp_server", ident)
        return self.sanitizer(token).context(result, "MCP_RESOURCE")

    async def prompt(self, ident, name, args):
        server = await self.owned.server(ident)
        template = next(
            (p for p in server.capabilities_json.get("prompts", []) if p["name"] == name), None
        )
        if not template:
            raise SafeError("NOT_FOUND")
        parameters = template.get("arguments", []) or []
        if (
            not isinstance(args, dict)
            or len(json.dumps(args).encode()) > 32000
            or any(not isinstance(k, str) or not isinstance(v, str) for k, v in args.items())
            or set(args) - {p["name"] for p in parameters}
            or any(p.get("required") and p["name"] not in args for p in parameters)
        ):
            raise SafeError("INVALID_TOOL_ARGUMENTS")
        token = await self.token(server)
        result = await self.client.get_prompt(server.server_url, name, args, token)
        audit(self.session, self.user_id, "MCP_PROMPT_LOADED", "mcp_server", ident)
        # All roles, including a supplied system role, are serialized as lower-trust data.
        return self.sanitizer(token).context(result, "MCP_PROMPT")
