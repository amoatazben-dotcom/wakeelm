import hashlib
import hmac
import json
import re
import secrets
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select

from app.core.exceptions import SafeError
from app.db.models import User
from app.db.models.integrations import GitHubConnection, GitHubRepository
from app.github.connections import GitHubConnections
from app.github.service import GitHubService
from app.integrations.http import IntegrationHTTP
from app.integrations.jobs import IntegrationJobs
from app.integrations.oauth import MCPOAuth, OAuthStateService, pkce
from app.services.workspace_service import WorkspaceService

router = APIRouter()


def dependencies(request):
    s = request.app.state
    return s.settings, s.sessions, s.secrets, s.limits


async def active(session, user_id):
    user = await session.get(User, user_id)
    if not user or not user.is_active:
        raise SafeError("INACTIVE")


@router.get("/integrations/{kind}/connect")
async def connect(kind: str, ticket: str, request: Request):
    settings, sessions, crypto, limits = dependencies(request)
    if kind not in {"github", "mcp"}:
        raise HTTPException(404)
    try:
        async with sessions() as session:
            states = OAuthStateService(session, crypto, settings)
            row, payload = await states.consume(ticket, "ticket", kind.upper() + "_TICKET")
            await active(session, row.user_id)
            verifier = secrets.token_urlsafe(48)
            redirect = states.callback_base() + (
                "/integrations/github/callback"
                if kind == "github"
                else "/integrations/mcp/oauth/callback"
            )
            payload.update(verifier=verifier, redirect_uri=redirect)
            state, nonce = await states.issue(row.user_id, kind.upper(), row.target_id, payload)
            if kind == "github":
                if (
                    not settings.github_client_id
                    or not settings.github_client_secret
                    or not settings.github_app_id
                ):
                    raise SafeError("GITHUB_APP_UNCONFIGURED")
                endpoint = "https://github.com/login/oauth/authorize"
                params = {
                    "client_id": settings.github_client_id,
                    "redirect_uri": redirect,
                    "state": state,
                    "code_challenge": pkce(verifier),
                    "code_challenge_method": "S256",
                }
            else:
                server = await MCPOAuth(
                    session, row.user_id, settings, crypto, limits
                ).owned.server(row.target_id, False)
                if server.server_url != payload["server_url"]:
                    raise SafeError("OAUTH_STATE_INVALID")
                endpoint = payload["authorization_endpoint"]
                params = {
                    "client_id": payload["client_id"],
                    "redirect_uri": redirect,
                    "state": state,
                    "response_type": "code",
                    "code_challenge": pkce(verifier),
                    "code_challenge_method": "S256",
                    "scope": " ".join(payload["scopes"]),
                    "resource": payload["server_url"],
                }
            await session.commit()
            response = RedirectResponse(endpoint + "?" + urlencode(params), status_code=302)
            response.set_cookie(
                "wakeelm_oauth_" + kind,
                nonce,
                max_age=settings.oauth_state_ttl_seconds,
                secure=True,
                httponly=True,
                samesite="lax",
                path="/integrations",
            )
            response.headers["Cache-Control"] = "no-store"
            response.headers["Referrer-Policy"] = "no-referrer"
            return response
    except SafeError as error:
        return JSONResponse({"error": error.code}, 400)


@router.get("/integrations/github/callback")
async def github_callback(
    request: Request, state: str = "", code: str = "", error: str | None = None
):
    settings, sessions, crypto, limits = dependencies(request)
    try:
        if error or not code or len(code) > 2000:
            raise SafeError("OAUTH_STATE_INVALID")
        async with sessions() as session:
            row, payload = await OAuthStateService(session, crypto, settings).consume(
                state, request.cookies.get("wakeelm_oauth_github"), "GITHUB"
            )
            await active(session, row.user_id)
            token = await IntegrationHTTP().request(
                "POST",
                "https://github.com/login/oauth/access_token",
                headers={"Accept": "application/json"},
                form={
                    "client_id": settings.github_client_id,
                    "client_secret": settings.github_client_secret.get_secret_value(),
                    "code": code,
                    "redirect_uri": payload["redirect_uri"],
                    "code_verifier": payload["verifier"],
                },
            )
            value = token.get("access_token")
            if not isinstance(value, str) or not value or len(value) > 10000:
                raise SafeError("AUTH_FAILED")
            identity = await GitHubService(value).get_authenticated_identity()
            connection = await GitHubConnections(session, row.user_id, crypto, settings).create_app(
                int(payload["installation_id"]), identity, value
            )
            workspace = WorkspaceService(session, row.user_id, settings, crypto, limits)
            await IntegrationJobs(workspace).enqueue(
                "GITHUB_SYNC", {"connection_id": connection.id}
            )
            await session.commit()
            response = JSONResponse({"status": "connected", "return_to": "Telegram"})
            response.delete_cookie("wakeelm_oauth_github", path="/integrations")
            response.headers["Cache-Control"] = "no-store"
            return response
    except SafeError as error:
        return JSONResponse({"error": error.code}, 400)


@router.get("/integrations/mcp/oauth/callback")
async def mcp_callback(
    request: Request,
    state: str = "",
    code: str = "",
    iss: str | None = None,
    error: str | None = None,
):
    settings, sessions, crypto, limits = dependencies(request)
    try:
        if error or not code or len(code) > 2000:
            raise SafeError("OAUTH_STATE_INVALID")
        async with sessions() as session:
            row, payload = await OAuthStateService(session, crypto, settings).consume(
                state, request.cookies.get("wakeelm_oauth_mcp"), "MCP"
            )
            await active(session, row.user_id)
            oauth = MCPOAuth(session, row.user_id, settings, crypto, limits)
            await oauth.exchange(row, payload, code, iss)
            await IntegrationJobs(
                WorkspaceService(session, row.user_id, settings, crypto, limits)
            ).enqueue("MCP_DISCOVER", {"server_id": row.target_id})
            await session.commit()
            response = JSONResponse({"status": "authorized", "return_to": "Telegram"})
            response.delete_cookie("wakeelm_oauth_mcp", path="/integrations")
            response.headers["Cache-Control"] = "no-store"
            return response
    except SafeError as error:
        return JSONResponse({"error": error.code}, 400)


@router.post("/webhooks/github")
async def github_webhook(request: Request):
    settings, sessions, crypto, limits = dependencies(request)
    if not settings.github_webhook_secret:
        raise HTTPException(503)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 1000000:
            raise HTTPException(413)
    expected = (
        "sha256="
        + hmac.new(
            settings.github_webhook_secret.get_secret_value().encode(), body, hashlib.sha256
        ).hexdigest()
    )
    if not hmac.compare_digest(request.headers.get("X-Hub-Signature-256", ""), expected):
        raise HTTPException(403)
    delivery = request.headers.get("X-GitHub-Delivery", "")
    if not re.fullmatch(r"[A-Za-z0-9-]{1,100}", delivery):
        raise HTTPException(400)
    key = "github:webhook:" + delivery
    if not await limits.redis.set(key, "processing", nx=True, ex=60):
        if await limits.redis.get(key) == b"done":
            return {"ok": True, "duplicate": True}
        raise HTTPException(503)
    try:
        data = json.loads(body)
        if not isinstance(data, dict):
            raise ValueError()
        event = request.headers.get("X-GitHub-Event", "")
        if event not in {
            "installation",
            "installation_repositories",
            "push",
            "pull_request",
            "issues",
            "ping",
        }:
            await limits.redis.set(key, "done", ex=86400)
            return {"ok": True, "ignored": True}
        installation = data.get("installation", {}).get("id")
        async with sessions() as session:
            connections = list(
                await session.scalars(
                    select(GitHubConnection).where(
                        GitHubConnection.connection_type == "APP",
                        GitHubConnection.installation_id == installation,
                        GitHubConnection.status == "ACTIVE",
                    )
                )
            )
            for connection in connections:
                if event == "installation" and data.get("action") in {"deleted", "suspend"}:
                    await GitHubConnections(session, connection.user_id, crypto, settings).revoke(
                        connection.id
                    )
                else:
                    removed = {x["id"] for x in data.get("repositories_removed", [])}
                    repos = list(
                        await session.scalars(
                            select(GitHubRepository).where(
                                GitHubRepository.github_connection_id == connection.id
                            )
                        )
                    )
                    for repo in repos:
                        if repo.github_repository_id in removed:
                            repo.is_disabled = True
                        if data.get("repository", {}).get("id") == repo.github_repository_id:
                            repo.metadata_json = {
                                **repo.metadata_json,
                                "remote_changed": event == "push",
                                "last_event": event,
                            }
                    if event in {"installation", "installation_repositories"}:
                        await IntegrationJobs(
                            WorkspaceService(session, connection.user_id, settings, crypto, limits)
                        ).enqueue("GITHUB_SYNC", {"connection_id": connection.id})
            await session.commit()
        await limits.redis.set(key, "done", ex=86400)
        return {"ok": True}
    except (ValueError, KeyError, TypeError):
        await limits.redis.delete(key)
        raise HTTPException(400) from None
    except Exception:
        await limits.redis.delete(key)
        raise HTTPException(503) from None
