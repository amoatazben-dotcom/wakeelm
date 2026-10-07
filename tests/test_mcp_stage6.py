import asyncio
from datetime import timedelta
from types import SimpleNamespace

import httpx
import pytest
from mcp_test_server import ControlledMCPServer
from test_agent import Models, never
from test_github_stage5 import settings

from app.agent.schemas import ToolRequest
from app.core.exceptions import SafeError
from app.core.limits import Limits
from app.db.base import now
from app.db.models.integrations import OAuthState
from app.integrations.http import IntegrationHTTP
from app.integrations.oauth import OAuthStateService, pkce
from app.mcp.client import MCPClient
from app.mcp.policy import validate_arguments
from app.mcp.service import MCPService
from app.services.agent_service import AgentService
from app.services.workspace_service import WorkspaceService
from app.tools.registry import ApprovalPending, ToolRegistry
from app.tools.router import ToolRouter


@pytest.fixture
async def mcp_stack(stack, tmp_path, monkeypatch):
    async def public(url):
        return {"8.8.8.8"}

    monkeypatch.setattr("app.integrations.http.public_addresses", public)
    cfg = settings(
        tmp_path, mcp_oauth_clients={"https://issuer.example.test": "test-public-client"}
    )
    server = ControlledMCPServer()
    transport = httpx.ASGITransport(app=server)
    http = IntegrationHTTP(transport=transport)
    client = MCPClient(cfg, transport_factory=lambda _: transport)
    service = MCPService(
        stack.session, stack.user.id, cfg, stack.secrets, Limits(stack.redis), client, http
    )
    ready = asyncio.Event()
    stop = asyncio.Event()

    async def serve():
        async with server.mcp.session_manager.run():
            ready.set()
            await stop.wait()

    task = asyncio.create_task(serve())
    await ready.wait()
    try:
        value = await service.add("Calendar", "https://mcp.example.test/mcp")
        await service.discover(value.id)
        yield SimpleNamespace(
            cfg=cfg, server=server, service=service, value=value, http=http, client=client
        )
    finally:
        stop.set()
        await task


async def review(m, name, capability="READ", integration="calendar"):
    tools = await m.service.tools(m.value.id)
    tool = next(t for t in tools if t.external_name == name)
    m.cfg.mcp_tool_policies[m.value.server_url + "#" + name] = {
        "fingerprint": tool.metadata_json["fingerprint"],
        "capability": capability,
        "integration": integration,
    }
    await m.service.enable(tool.id)
    return tool


async def test_sdk_discovers_tools_resources_prompts_and_default_denial(stack, mcp_stack):
    m = mcp_stack
    assert m.value.status == "CONNECTED" and m.value.protocol_version
    tools = await m.service.tools(m.value.id)
    assert len(tools) == 3 and not any(t.is_enabled for t in tools)
    with pytest.raises(SafeError, match="MCP_REVIEW_REQUIRED"):
        await m.service.enable(tools[0].id)
    danger = next(t for t in tools if t.external_name == "dangerous_shell")
    assert danger.risk_level == "CRITICAL"
    assert (await m.service.resources(m.value.id))[0].uri == "test://project/readme"
    assert m.value.capabilities_json["prompts"][0]["name"] == "helpful_prompt"


async def test_read_tool_policy_sanitizer_and_registry(stack, tmp_path, mcp_stack):
    m = mcp_stack
    tool = await review(m, "read_record")
    w = WorkspaceService(stack.session, stack.user.id, m.cfg, stack.secrets, Limits(stack.redis))
    workspace = await w.ingest("main.py", b"VALUE = 1\n")
    agents = AgentService(w, Models())
    job = await agents.create(workspace.id, "READ_ONLY", "Calendar read project")
    job.result_json = {"mcp_servers": [m.value.id]}
    registry = ToolRegistry(w, job, never)
    registry.mcp = m.service
    result = await registry.execute(
        ToolRequest(tool_name="mcp." + tool.id.replace("-", ""), arguments={"query": "project"})
    )
    assert result["origin"] == "TOOL_RESULT" and result["trust"] == "UNTRUSTED"
    assert "github_pat_" not in result["text"] and "[REDACTED]" in result["text"]
    assert m.server.calls == [("read", "project")]
    with pytest.raises(SafeError, match="INVALID_TOOL_ARGUMENTS"):
        await registry.execute(
            ToolRequest(tool_name="mcp." + tool.id.replace("-", ""), arguments={"query": 42})
        )


async def test_write_tool_requires_bound_approval_cross_user_denial(stack, tmp_path, mcp_stack):
    m = mcp_stack
    tool = await review(m, "write_mock", "CREATE")
    w = WorkspaceService(stack.session, stack.user.id, m.cfg, stack.secrets, Limits(stack.redis))
    workspace = await w.ingest("main.py", b"VALUE = 1\n")
    agents = AgentService(w, Models())
    job = await agents.create(workspace.id, "WORKSPACE", "Calendar meeting")
    job.result_json = {"mcp_servers": [m.value.id]}
    registry = ToolRegistry(w, job, never)
    registry.mcp = m.service
    request = ToolRequest(
        tool_name="mcp." + tool.id.replace("-", ""), arguments={"title": "Project meeting"}
    )
    with pytest.raises(ApprovalPending):
        await registry.execute(request)
    assert not m.server.calls
    approval = (await agents.pending(job.id))[0]
    from app.agent.approvals import ApprovalService

    with pytest.raises(SafeError, match="NOT_FOUND"):
        await ApprovalService(stack.session, 999, m.cfg).decide(approval.id, True)
    await agents.approvals.decide(approval.id, True)
    await registry.execute(request)
    assert m.server.calls == [("write", "Project meeting")]
    request.arguments = {"title": "Different meeting"}
    with pytest.raises(ApprovalPending):
        await registry.execute(request)


async def test_resource_prompt_lower_trust_and_removed_server_denied(stack, mcp_stack):
    m = mcp_stack
    resource = await m.service.read_resource(m.value.id, "test://project/readme")
    prompt = await m.service.prompt(m.value.id, "helpful_prompt", {"topic": "Task"})
    assert resource["origin"] == "MCP_RESOURCE" and prompt["origin"] == "MCP_PROMPT"
    assert "SYSTEM" in prompt["text"] and prompt["trust"] == "UNTRUSTED"
    with pytest.raises(SafeError, match="NOT_FOUND"):
        await m.service.read_resource(m.value.id, "file:///etc/passwd")
    await m.service.remove(m.value.id)
    with pytest.raises(SafeError):
        await m.service.read_resource(m.value.id, "test://project/readme")


async def test_schema_change_forces_re_review(stack, mcp_stack):
    m = mcp_stack
    tool = await review(m, "read_record")
    original = m.client.discover

    async def changed(*args):
        value = await original(*args)
        item = next(x for x in value["tools"] if x["name"] == "read_record")
        item["inputSchema"]["properties"]["write"] = {"type": "boolean"}
        return value

    m.client.discover = changed
    await m.service.discover(m.value.id)
    await stack.session.refresh(tool)
    assert not tool.is_enabled and tool.metadata_json["needs_review"]
    with pytest.raises(SafeError):
        await m.service.enable(tool.id)


async def test_oauth_pkce_issuer_encryption_isolation_refresh(stack, mcp_stack):
    m = mcp_stack
    m.server.protected = True
    m.value.status = "AUTH_REQUIRED"
    url = await m.service.oauth.start(m.value.id, ["read"])
    assert "/integrations/mcp/connect?ticket=" in url
    states = m.service.oauth.states
    ticket = url.split("ticket=")[1]
    row, config = await states.consume(ticket, "ticket", "MCP_TICKET")
    verifier = "v" * 64
    config.update(
        verifier=verifier, redirect_uri="https://bot.example.test/integrations/mcp/oauth/callback"
    )
    m.server.codes["one-code"] = {
        "challenge": pkce(verifier),
        "redirect_uri": config["redirect_uri"],
        "scope": "read",
    }
    with pytest.raises(SafeError, match="OAUTH_ISSUER_MISMATCH"):
        await m.service.oauth.exchange(row, config, "one-code", "https://evil.example.test")
    credential = await m.service.oauth.exchange(
        row, config, "one-code", "https://issuer.example.test"
    )
    assert (
        "access-one" not in credential.encrypted_access_token
        and "refresh-one" not in credential.encrypted_refresh_token
    )
    await m.service.discover(m.value.id)
    assert m.value.status == "CONNECTED"
    credential.expires_at = now() - timedelta(seconds=1)
    await stack.session.commit()
    assert await m.service.token(m.value) == "access-two" and m.server.refreshes == 1
    assert credential.scopes_json == ["read"]
    alien = MCPService(
        stack.session, 999, m.cfg, stack.secrets, Limits(stack.redis), m.client, m.http
    )
    with pytest.raises(SafeError):
        await alien.owned.server(m.value.id)


async def test_oauth_state_nonce_expiry_replay(stack, mcp_stack):
    m = mcp_stack
    states = OAuthStateService(stack.session, stack.secrets, m.cfg)
    state, nonce = await states.issue(stack.user.id, "MCP", m.value.id, {"secret": "verifier"})
    with pytest.raises(SafeError, match="OAUTH_STATE_INVALID"):
        await states.consume(state, "wrong", "MCP")
    await states.consume(state, nonce, "MCP")
    with pytest.raises(SafeError, match="OAUTH_STATE_INVALID"):
        await states.consume(state, nonce, "MCP")
    state, nonce = await states.issue(stack.user.id, "MCP", m.value.id, {})
    record = await stack.session.get(
        OAuthState, __import__("hashlib").sha256(state.encode()).hexdigest()
    )
    record.expires_at = now() - timedelta(seconds=1)
    await stack.session.commit()
    with pytest.raises(SafeError, match="OAUTH_STATE_INVALID"):
        await states.consume(state, nonce, "MCP")


@pytest.mark.parametrize(
    "url",
    [
        "http://public.example/mcp",
        "file:///etc/passwd",
        "ftp://public.example/mcp",
        "https://127.0.0.1/mcp",
        "https://169.254.169.254/mcp",
        "https://10.0.0.1/mcp",
        "https://localhost/mcp",
        "https://service.railway.internal/mcp",
    ],
)
async def test_production_url_ssrf_blocked(url):
    from app.integrations.http import validate_https

    with pytest.raises(SafeError):
        await validate_https(url)


async def test_arbitrary_stdio_and_disabled_tool_denied(stack, mcp_stack):
    m = mcp_stack
    with pytest.raises(SafeError, match="TRANSPORT_DENIED"):
        await m.service.add("Shell", "https://mcp.example.test/mcp", "stdio")
    tool = (await m.service.tools(m.value.id))[0]
    with pytest.raises(SafeError, match="TOOL_DISABLED"):
        await m.service.call(tool, {}, "WORKSPACE")


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "object", "properties": {"x": {"$ref": "https://evil.example/schema"}}},
        {"type": "string", "pattern": "(a+)+"},
        {"type": "unknown"},
    ],
)
def test_unsafe_schema_rejected(schema):
    with pytest.raises(SafeError):
        validate_arguments(schema, {})


async def test_scope_escalation_and_database_arbitrary_sql_blocked(stack, mcp_stack):
    m = mcp_stack
    with pytest.raises(SafeError, match="SCOPE_REQUIRED"):
        await m.service.oauth.start(m.value.id, ["admin"])
    tool = await review(m, "read_record", integration="database")
    with pytest.raises(SafeError, match="DATABASE_WRITE_DENIED"):
        await m.service.call(tool, {"query": "SELECT * FROM users"}, "READ_ONLY")


def test_tool_router_relevance_not_blanket_exposure():
    router = ToolRouter()
    server = SimpleNamespace(id="a", name="Calendar")
    tool = SimpleNamespace(metadata_json={"integration": "calendar"})
    assert router.relevant("create meeting tomorrow", server, tool)
    assert not router.relevant("inspect database schema", server, tool)


async def test_oauth_wrong_pkce_refresh_failure_and_returned_scope_escalation(stack, mcp_stack):
    m = mcp_stack
    config = await m.service.oauth.discover(m.value)
    config.update(
        scopes=["read"],
        server_url=m.value.server_url,
        verifier="wrong-verifier",
        redirect_uri="https://bot.example.test/integrations/mcp/oauth/callback",
    )
    m.server.codes["bad-code"] = {
        "challenge": pkce("expected-verifier"),
        "redirect_uri": config["redirect_uri"],
        "scope": "read",
    }
    row = SimpleNamespace(target_id=m.value.id, user_id=stack.user.id)
    with pytest.raises(SafeError, match="AUTH_FAILED"):
        await m.service.oauth.exchange(row, config, "bad-code", "https://issuer.example.test")
    with pytest.raises(SafeError, match="OAUTH_SCOPE_ESCALATION"):
        await m.service.oauth.save(
            m.value,
            config,
            {
                "access_token": "access-one",
                "refresh_token": "refresh-one",
                "token_type": "Bearer",
                "expires_in": 3600,
                "scope": "read admin",
            },
        )
    credential = await m.service.oauth.save(
        m.value,
        config,
        {
            "access_token": "access-one",
            "refresh_token": "refresh-one",
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": "read",
        },
    )
    credential.expires_at = now() - timedelta(seconds=1)
    m.server.fail_refresh = True
    await stack.session.commit()
    with pytest.raises(SafeError, match="AUTH_FAILED"):
        await m.service.token(m.value)
    assert (
        credential.scopes_json == ["read"]
        and stack.secrets.decrypt(credential.encrypted_access_token) == "access-one"
    )


async def test_sdk_operation_deadline(mcp_stack):
    m = mcp_stack
    original = m.client.transport_factory

    class SlowTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            await asyncio.sleep(0.1)
            return await original(str(request.url)).handle_async_request(request)

    m.client.transport_factory = lambda _: SlowTransport()
    m.cfg.mcp_call_timeout_seconds = 0.01
    with pytest.raises(SafeError, match="TIMEOUT"):
        await m.client.discover(m.value.server_url)


async def test_resource_templates_semantic_namespace_and_policy_drift(stack, mcp_stack):
    m = mcp_stack
    assert (
        m.value.capabilities_json["resource_templates"][0]["uriTemplate"] == "test://project/{name}"
    )
    tool = await review(m, "read_record")
    registry = await registry_for(m, stack, "READ_ONLY")
    from app.mcp.adapter import tool_namespace

    name = tool_namespace(tool)
    assert name.startswith("mcp.calendar.read_record_")
    assert name.replace(".", "__") in {x["function"]["name"] for x in registry.schemas()}
    m.cfg.mcp_tool_policies[m.value.server_url + "#read_record"]["capability"] = "UPDATE"
    with pytest.raises(SafeError, match="MCP_REVIEW_REQUIRED"):
        await registry.execute(ToolRequest(tool_name=name, arguments={"query": "record"}))
    assert not m.server.calls


async def test_medium_draft_requires_review_and_approval(stack, mcp_stack):
    m = mcp_stack
    tool = await review(m, "write_mock", "CREATE")
    m.cfg.mcp_tool_policies[m.value.server_url + "#write_mock"].update(
        risk="MEDIUM", artifact="DRAFT"
    )
    await m.service.enable(tool.id)
    assert tool.risk_level == "MEDIUM" and tool.requires_approval
    with pytest.raises(SafeError, match="APPROVAL_REQUIRED"):
        await m.service.call(tool, {"title": "draft"}, "WORKSPACE")


async def test_offline_server_is_safe_and_no_secret_diagnostic(mcp_stack):
    m = mcp_stack

    class Offline(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            raise httpx.ConnectError("password=must-never-leak", request=request)

    m.client.transport_factory = lambda _: Offline()
    with pytest.raises(SafeError, match="OFFLINE") as error:
        await m.client.discover(m.value.server_url)
    assert "password" not in str(error.value)


async def test_additional_scope_failure_bound_to_server_and_audited(stack, mcp_stack):
    from sqlalchemy import select

    from app.db.models import AuditLog
    from app.mcp.adapter import tool_namespace

    m = mcp_stack
    tool = await review(m, "read_record")
    m.cfg.mcp_tool_policies[m.value.server_url + "#read_record"]["required_scopes"] = ["read"]
    await m.service.enable(tool.id)
    registry = await registry_for(m, stack, "READ_ONLY")
    with pytest.raises(SafeError, match="SCOPE_REQUIRED"):
        await registry.execute(
            ToolRequest(tool_name=tool_namespace(tool), arguments={"query": "record"})
        )
    assert registry.job.result_json["auth_server_id"] == m.value.id
    actions = set(await stack.session.scalars(select(AuditLog.action)))
    assert "MCP_TOOL_CALL_DENIED" in actions


async def registry_for(m, stack, mode):
    w = WorkspaceService(stack.session, stack.user.id, m.cfg, stack.secrets, Limits(stack.redis))
    workspace = await w.ingest("main.py", b"VALUE = 1\n")
    job = await AgentService(w, Models()).create(workspace.id, mode, "calendar record")
    registry = ToolRegistry(w, job, never)
    registry.mcp = m.service
    await registry.hydrate()
    return registry


async def test_resume_auth_keeps_same_job_step_and_rechecks_scope(stack, mcp_stack):
    m = mcp_stack
    tool = await review(m, "read_record")
    registry = await registry_for(m, stack, "READ_ONLY")
    job = registry.job
    job.status, job.failure_code = "FAILED", "SCOPE_REQUIRED"
    job.result_json = {"auth_server_id": m.value.id}
    await stack.session.commit()
    service = AgentService(registry.workspaces, Models())
    resumed = await service.resume_after_auth(job.id)
    assert resumed.id == job.id and resumed.current_step == 0 and resumed.status == "QUEUED"
    assert resumed.failure_code is None
    from app.services.workspace_service import WorkspaceService

    alien = AgentService(
        WorkspaceService(stack.session, 999, m.cfg, stack.secrets, Limits(stack.redis)), Models()
    )
    with pytest.raises(SafeError, match="NOT_FOUND"):
        await alien.resume_after_auth(job.id)
    assert tool.is_enabled
