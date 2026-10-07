import hashlib
import json
import secrets
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, update

from app.db.base import now
from app.db.models import AuditLog, Model, Provider, User
from app.db.models.agent import AgentJob, Approval
from app.db.models.integrations import GitHubConnection, GitHubRepository, MCPServer
from app.db.models.platform import (
    AdminAudit,
    AdminIdentity,
    FeatureFlag,
    UsageEntry,
    UserPlan,
)
from app.db.models.projects import Workspace
from app.integrations.http import IntegrationHTTP
from app.platform.admin_auth import PERMISSIONS, admin, session_id, verify_identity
from app.platform.flags import DEFAULTS
from app.platform.telemetry import render_metrics
from app.platform.usage import DEFAULT_LIMITS

router = APIRouter(prefix="/admin")


@router.get("/login")
async def login(request: Request):
    state = request.app.state
    settings = state.settings
    if not settings.admin_oidc_issuer:
        raise HTTPException(503, "OIDC configuration required")
    await state.limits.cooldown("admin-login:" + request.client.host, 2)
    ticket, verifier, nonce = session_id(), secrets.token_urlsafe(48), session_id()
    await state.redis.set(
        "admin:login:" + ticket,
        state.secrets.encrypt(json.dumps({"verifier": verifier, "nonce": nonce})),
        ex=300,
    )
    challenge = (
        __import__("base64")
        .urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    params = {
        "client_id": settings.admin_oidc_client_id,
        "response_type": "code",
        "redirect_uri": settings.public_base_url.rstrip("/") + "/admin/callback",
        "scope": "openid",
        "state": ticket,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "max_age": "0",
    }
    response = RedirectResponse(settings.admin_oidc_authorize_url + "?" + urlencode(params), 302)
    response.set_cookie(
        "__Host-wakeelm_login",
        ticket,
        secure=True,
        httponly=True,
        samesite="lax",
        path="/",
        max_age=300,
    )
    return response


@router.get("/callback")
async def callback(request: Request, code: str, state: str):
    app = request.app.state
    if not secrets.compare_digest(request.cookies.get("__Host-wakeelm_login", ""), state):
        raise HTTPException(400)
    encrypted = await app.redis.getdel("admin:login:" + state)
    if not encrypted:
        raise HTTPException(400)
    data = json.loads(app.secrets.decrypt(encrypted.decode()))
    s = app.settings
    form = {
        "grant_type": "authorization_code",
        "client_id": s.admin_oidc_client_id,
        "code": code,
        "code_verifier": data["verifier"],
        "redirect_uri": s.public_base_url.rstrip("/") + "/admin/callback",
    }
    if s.admin_oidc_client_secret:
        form["client_secret"] = s.admin_oidc_client_secret.get_secret_value()
    try:
        tokens = await IntegrationHTTP(timeout=10).request(
            "POST", s.admin_oidc_token_url, form=form
        )
        subject = await verify_identity(tokens["id_token"], s, data["nonce"])
    except Exception:
        raise HTTPException(401, "OIDC login failed") from None
    sid, csrf = session_id(), session_id()
    await app.redis.set(
        "admin:session:" + sid,
        app.secrets.encrypt(json.dumps({"subject": subject, "csrf": csrf})),
        ex=s.admin_session_seconds,
    )
    response = RedirectResponse("/admin-web/", 302)
    response.delete_cookie("__Host-wakeelm_login", secure=True, httponly=True, path="/")
    response.set_cookie(
        "__Host-wakeelm_admin",
        sid,
        secure=True,
        httponly=True,
        samesite="lax",
        path="/",
        max_age=s.admin_session_seconds,
    )
    return response


@router.get("/me")
async def me(request: Request):
    subject, role = await admin(request)
    csrf = None
    sid = request.cookies.get("__Host-wakeelm_admin")
    if sid:
        encrypted = await request.app.state.redis.get("admin:session:" + sid)
        if encrypted:
            csrf = json.loads(request.app.state.secrets.decrypt(encrypted.decode()))["csrf"]
    return {
        "subject": subject,
        "role": role,
        "permissions": sorted(PERMISSIONS[role]),
        "csrf": csrf,
    }


@router.post("/logout")
async def logout(request: Request):
    await admin(request)
    sid = request.cookies.get("__Host-wakeelm_admin")
    if sid:
        await request.app.state.redis.delete("admin:session:" + sid)
    response = PlainTextResponse("Logged out")
    response.delete_cookie("__Host-wakeelm_admin", secure=True, httponly=True, path="/")
    return response


COLLECTIONS = {
    "users": (User, ["id", "language", "is_active", "last_seen_at"]),
    "providers": (Provider, ["id", "user_id", "name", "status", "last_checked_at"]),
    "models": (
        Model,
        ["id", "provider_id", "display_name", "status", "is_available", "pricing_json"],
    ),
    "jobs": (
        AgentJob,
        [
            "id",
            "user_id",
            "workspace_id",
            "status",
            "current_step",
            "model_requests",
            "input_tokens",
            "output_tokens",
            "tool_calls_count",
            "elapsed_ms",
            "failure_code",
            "created_at",
        ],
    ),
    "workspaces": (Workspace, ["id", "user_id", "type", "status", "size_bytes", "file_count"]),
    "repositories": (
        GitHubRepository,
        ["id", "github_connection_id", "full_name", "default_branch"],
    ),
    "github": (GitHubConnection, ["id", "user_id", "connection_type", "status"]),
    "mcp": (MCPServer, ["id", "user_id", "name", "status"]),
    "flags": (FeatureFlag, ["key", "enabled", "targets_json"]),
    "quotas": (UserPlan, ["user_id", "plan", "overrides_json"]),
    "usage": (
        UsageEntry,
        [
            "id",
            "user_id",
            "provider_id",
            "model_id",
            "job_id",
            "operation",
            "input_tokens",
            "output_tokens",
            "estimated_cost",
            "actual_cost",
            "duration_ms",
            "status",
            "created_at",
        ],
    ),
    "audit": (
        AuditLog,
        ["id", "user_id", "action", "entity_type", "entity_id", "metadata_json", "created_at"],
    ),
    "admin-audit": (
        AdminAudit,
        ["id", "subject", "action", "target", "metadata_json", "created_at"],
    ),
}


@router.get("/data/{collection}")
async def collection(
    request: Request,
    collection: str,
    page: int = 0,
    user_id: int | None = None,
    job_id: str | None = None,
    status: str | None = None,
    action: str | None = None,
    since: str | None = None,
    until: str | None = None,
    risk: str | None = None,
    integration: str | None = None,
):
    await admin(request, "audit" if collection in {"audit", "admin-audit"} else "read")
    if collection not in COLLECTIONS or not 0 <= page <= 10000:
        raise HTTPException(400)
    model, fields = COLLECTIONS[collection]
    stmt = select(model)
    if collection == "repositories" and user_id is not None:
        stmt = stmt.join(GitHubConnection).where(GitHubConnection.user_id == user_id)
    for name, value in [
        ("user_id", user_id),
        ("job_id", job_id),
        ("status", status),
        ("action", action),
    ]:
        if value is not None and hasattr(model, name):
            stmt = stmt.where(getattr(model, name) == value)
    if collection == "audit":
        if job_id:
            stmt = stmt.where(AuditLog.entity_type == "agent_job", AuditLog.entity_id == job_id)
        if risk:
            stmt = stmt.where(AuditLog.metadata_json["risk"].as_string() == risk)
        if integration:
            stmt = stmt.where(AuditLog.metadata_json["integration"].as_string() == integration)
    from datetime import datetime

    try:
        if since and hasattr(model, "created_at"):
            stmt = stmt.where(model.created_at >= datetime.fromisoformat(since))
        if until and hasattr(model, "created_at"):
            stmt = stmt.where(model.created_at <= datetime.fromisoformat(until))
    except ValueError:
        raise HTTPException(400) from None
    async with request.app.state.sessions() as session:
        total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
        primary = list(model.__table__.primary_key.columns)[0]
        rows = list(
            await session.scalars(stmt.order_by(primary.desc()).offset(page * 50).limit(50))
        )
        values = [{field: getattr(row, field) for field in fields} for row in rows]
        if collection == "jobs" and rows:
            usage = list(
                await session.scalars(
                    select(UsageEntry)
                    .where(
                        UsageEntry.job_id.in_([row.id for row in rows]),
                        UsageEntry.operation == "model",
                    )
                    .order_by(UsageEntry.id.desc())
                )
            )
            for value in values:
                calls = [entry for entry in usage if entry.job_id == value["id"]]
                value["provider_id"] = calls[0].provider_id if calls else None
                value["model_id"] = calls[0].model_id if calls else None
                value["estimated_cost"] = str(sum(entry.estimated_cost or 0 for entry in calls))
    return {"items": values, "total": total, "page": page}


class AdminChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool | None = None
    targets: dict = Field(default_factory=dict)
    plan: str | None = None
    limits: dict = Field(default_factory=dict)
    role: str | None = None
    confirmation: str | None = Field(default=None, max_length=100)


@router.post("/control/{kind}/{target}")
async def control(request: Request, kind: str, target: str, change: AdminChange):
    permission = {
        "flag": "security" if target.startswith("disable_") else "operate",
        "identity": "security",
        "user-data": "security",
        "quota": "quotas",
        "user": "support",
        "job": "support",
        "provider": "operate",
        "mcp": "security",
    }.get(kind)
    if not permission:
        raise HTTPException(400)
    subject, _ = await admin(request, permission)
    async with request.app.state.sessions() as session:
        if kind == "flag":
            if target not in DEFAULTS and not target.startswith("disable_provider_"):
                raise HTTPException(400)
            if set(change.targets) - {"users", "plans", "percentage"}:
                raise HTTPException(400)
            if "percentage" in change.targets and (
                not isinstance(change.targets["percentage"], int)
                or not 0 <= change.targets["percentage"] <= 100
            ):
                raise HTTPException(400)
            if "users" in change.targets and (
                not isinstance(change.targets["users"], list)
                or len(change.targets["users"]) > 1000
                or any(type(value) is not int or value < 1 for value in change.targets["users"])
            ):
                raise HTTPException(400)
            if "plans" in change.targets and (
                not isinstance(change.targets["plans"], list)
                or any(value not in DEFAULT_LIMITS for value in change.targets["plans"])
            ):
                raise HTTPException(400)
            # Emergency global stop cannot accidentally be a partial rollout.
            if target.startswith("disable_") and change.targets:
                raise HTTPException(400)
            await session.merge(
                FeatureFlag(key=target, enabled=bool(change.enabled), targets_json=change.targets)
            )
        elif kind == "quota":
            if change.plan not in DEFAULT_LIMITS or set(change.limits) - set(
                DEFAULT_LIMITS["FREE"]
            ):
                raise HTTPException(400)
            if any(
                not isinstance(v, (int, float)) or isinstance(v, bool) or not 0 <= v <= 1e12
                for v in change.limits.values()
            ):
                raise HTTPException(400)
            if not await session.get(User, int(target)):
                raise HTTPException(404)
            await session.merge(
                UserPlan(user_id=int(target), plan=change.plan, overrides_json=change.limits)
            )
        elif kind == "identity":
            if change.role not in PERMISSIONS or target == subject:
                raise HTTPException(400)
            await session.merge(
                AdminIdentity(subject=target, role=change.role, enabled=bool(change.enabled))
            )
        elif kind == "user-data":
            if change.confirmation != target or not target.isascii() or not target.isdigit():
                raise HTTPException(400, "Explicit user ID confirmation required")
            from app.platform.retention import RetentionService

            state = request.app.state
            await RetentionService(
                session, state.settings, state.secrets, state.limits
            ).delete_user_data(int(target))
        elif kind == "job":
            job = await session.get(AgentJob, target, with_for_update=True)
            if not job:
                raise HTTPException(404)
            from app.agent.approvals import TERMINAL

            if job.status not in TERMINAL:
                await request.app.state.redis.set("agent:cancel:" + job.id, "1", ex=3600)
                job.status = (
                    "CANCEL_REQUESTED" if job.status in {"RUNNING", "PLANNING"} else "CANCELLED"
                )
                await session.execute(
                    update(Approval)
                    .where(Approval.job_id == job.id, Approval.status == "PENDING")
                    .values(status="CANCELLED", decided_at=now())
                )
        else:
            model = {"user": User, "provider": Provider, "mcp": MCPServer}[kind]
            ident = int(target) if kind != "mcp" else target
            row = await session.get(model, ident, with_for_update=True)
            if not row:
                raise HTTPException(404)
            if kind == "user":
                row.is_active = bool(change.enabled)
            else:
                # Re-enabling needs connection verification through normal user workflow.
                if change.enabled:
                    raise HTTPException(400)
                row.status = "DISABLED"
        session.add(
            AdminAudit(
                subject=subject,
                action=kind.upper() + "_CHANGED",
                target=target,
                metadata_json=change.model_dump(exclude_none=True),
            )
        )
        await session.commit()
    return {"status": "ok"}


@router.get("/health")
async def system_health(request: Request):
    await admin(request)
    from app.api.health import ready
    from app.platform.version import metadata

    async with request.app.state.sessions() as session:
        queue = await session.scalar(
            select(func.count()).select_from(AgentJob).where(AgentJob.status == "QUEUED")
        )
        pending = await session.scalar(
            select(func.count()).select_from(Approval).where(Approval.status == "PENDING")
        )
    readiness = await ready(request)
    return {
        "readiness": json.loads(readiness.body),
        "queue_depth": queue,
        "pending_approvals": pending,
        "release": metadata(request.app.state.settings),
    }


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics(request: Request):
    await admin(request)
    from app.platform.telemetry import COUNTERS

    async with request.app.state.sessions() as session:
        COUNTERS["queue_depth"] = await session.scalar(
            select(func.count()).select_from(AgentJob).where(AgentJob.status == "QUEUED")
        )
        COUNTERS["active_jobs"] = await session.scalar(
            select(func.count())
            .select_from(AgentJob)
            .where(AgentJob.status.in_(["RUNNING", "PLANNING"]))
        )
        COUNTERS["workspace_storage"] = await session.scalar(
            select(func.coalesce(func.sum(Workspace.size_bytes), 0)).where(
                Workspace.status != "DELETED"
            )
        )
    pool = request.app.state.engine.sync_engine.pool
    COUNTERS["db_pool_usage"] = getattr(pool, "checkedout", lambda: 0)()
    return PlainTextResponse(render_metrics(), media_type="text/plain; version=0.0.4")
