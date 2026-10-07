import json
from datetime import timedelta
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from sqlalchemy import func, select

from app.core.exceptions import SafeError
from app.db.base import now
from app.db.models.platform import FeatureFlag, UsageEntry, UserPlan
from app.platform.admin_auth import JWKS_CACHE, PERMISSIONS, verify_identity
from app.platform.circuit import CircuitBreaker
from app.platform.flags import FeatureFlags
from app.platform.telemetry import (
    ErrorTracker,
    metric,
    render_metrics,
    trace_context,
    trace_headers,
)
from app.platform.usage import QuotaEngine


async def test_usage_reservations_and_cost_token_message_limits(stack):
    engine = QuotaEngine(stack.session, stack.user.id)
    stack.session.add(
        UserPlan(
            user_id=stack.user.id,
            plan="FREE",
            overrides_json={"tokens_day": 10, "messages_day": 1, "daily_spend": 0.15},
        )
    )
    await stack.session.flush()
    await engine.reserve("message")
    with pytest.raises(SafeError, match="QUOTA_EXCEEDED"):
        await engine.reserve("message")
    row = await engine.reserve("model", input_tokens=2, output_tokens=3, cost=None)
    assert str(row.estimated_cost) == "0.10"
    await stack.session.commit()
    with pytest.raises(SafeError, match="QUOTA_EXCEEDED"):
        await engine.reserve("model", input_tokens=2, output_tokens=1)
    with pytest.raises(SafeError, match="QUOTA_EXCEEDED"):
        await engine.reserve("model", input_tokens=9, cost=0)
    summary = await engine.summary()
    assert summary["today"]["tokens"] == 5
    assert summary["today"]["unknown_price_requests"] == 1
    assert await stack.session.scalar(select(func.count()).select_from(UsageEntry)) == 2


async def test_flag_targeting_and_global_stops(stack):
    flags = FeatureFlags(stack.session, stack.user.id)
    assert not await flags.enabled("disable_external_writes")
    stack.session.add(FeatureFlag(key="disable_external_writes", enabled=True, targets_json={}))
    stack.session.add(FeatureFlag(key="multi_agent", enabled=True, targets_json={"users": [999]}))
    await stack.session.flush()
    with pytest.raises(SafeError, match="KILL_SWITCH_ACTIVE"):
        await flags.deny_if("disable_external_writes")
    assert not await flags.enabled("multi_agent")
    assert await FeatureFlags(stack.session, 999).enabled("multi_agent")


async def test_shared_circuit_open_half_open_single_probe_and_reset(stack):
    breaker = CircuitBreaker(stack.redis, "provider:1", threshold=2, cooldown=30)
    await breaker.before()
    await breaker.failure()
    await breaker.failure()
    with pytest.raises(SafeError, match="PROVIDER_OFFLINE"):
        await CircuitBreaker(stack.redis, "provider:1", threshold=2).before()
    await stack.redis.delete(breaker.key + ":open")
    probe = CircuitBreaker(stack.redis, "provider:1", threshold=2)
    await probe.before()
    with pytest.raises(SafeError):
        await CircuitBreaker(stack.redis, "provider:1", threshold=2).before()
    await probe.success()
    await breaker.before()


async def test_oidc_signature_issuer_audience_mfa_and_nonce():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    public.update(kid="test-key", use="sig")
    settings = SimpleNamespace(
        admin_oidc_issuer="https://id.example",
        admin_oidc_jwks_url="https://id.example/keys",
        admin_oidc_audience="wakeelm-admin",
        admin_oidc_client_id="client",
        admin_require_mfa=True,
    )

    class HTTP:
        async def request(self, *args):
            return {"keys": [public]}

    claims = {
        "iss": settings.admin_oidc_issuer,
        "sub": "operator-123",
        "aud": "client",
        "iat": now(),
        "exp": now() + timedelta(minutes=5),
        "amr": ["mfa"],
        "nonce": "expected-nonce",
    }

    def token(changes=None):
        return jwt.encode(
            claims | (changes or {}), key, algorithm="RS256", headers={"kid": "test-key"}
        )

    JWKS_CACHE.clear()
    assert await verify_identity(token(), settings, "expected-nonce", HTTP()) == "operator-123"
    for changes in [
        {"iss": "https://evil.example"},
        {"aud": "other"},
        {"amr": ["pwd"]},
        {"nonce": "wrong"},
        {"exp": now() - timedelta(minutes=1)},
    ]:
        with pytest.raises(HTTPException) as exc:
            await verify_identity(token(changes), settings, "expected-nonce", HTTP())
        assert exc.value.status_code == 401
    assert "security" not in PERMISSIONS["ADMIN"]
    assert "support" not in PERMISSIONS["AUDITOR"]


def test_trace_metrics_and_error_payload_redaction():
    with trace_context(
        "00-" + "a" * 32 + "-" + "b" * 16 + "-01", job_id="job", token="secret"
    ) as trace:
        assert trace["trace_id"] == "a" * 32 and "token" not in trace
        assert trace_headers()["traceparent"].startswith("00-" + "a" * 32)
        metric("model_calls")
        metric("provider_latency", 0.2, observe=True)
        try:
            raise ValueError("password=secret-should-not-appear")
        except ValueError as exc:
            event = ErrorTracker().capture(exc, "0.8.0")
        assert "secret" not in json.dumps(event)
    assert "wakeelm_model_calls" in render_metrics()
    assert "wakeelm_provider_latency_bucket" in render_metrics()


async def test_real_admin_api_roles_csrf_metadata_and_audited_writes(stack, monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.api.admin import router
    from app.core.limits import Limits
    from app.db.models.platform import AdminAudit, AdminIdentity

    app = FastAPI()
    app.include_router(router)
    app.state.sessions, app.state.redis, app.state.limits = (
        stack.sessions,
        stack.redis,
        Limits(stack.redis),
    )
    app.state.secrets = stack.secrets
    app.state.settings = SimpleNamespace(
        public_base_url="https://agent.example", admin_super_subjects=[]
    )

    async def identity(token, settings):
        return token

    async def no_cooldown(*args):
        pass

    monkeypatch.setattr("app.platform.admin_auth.verify_identity", identity)
    monkeypatch.setattr(app.state.limits, "cooldown", no_cooldown)
    stack.session.add_all(
        [
            AdminIdentity(subject="reader", role="READ_ONLY", enabled=True),
            AdminIdentity(subject="super", role="SUPER_ADMIN", enabled=True),
        ]
    )
    await stack.session.commit()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://agent.example"
    ) as client:
        assert (await client.get("/admin/data/users")).status_code == 401
        response = await client.get("/admin/data/users", headers={"Authorization": "Bearer reader"})
        assert response.status_code == 200
        assert "telegram_username" not in response.text and "encrypted" not in response.text
        assert (
            await client.get("/admin/data/audit", headers={"Authorization": "Bearer reader"})
        ).status_code == 403
        path = "/admin/control/flag/disable_external_writes"
        assert (
            await client.post(
                path, json={"enabled": True}, headers={"Authorization": "Bearer reader"}
            )
        ).status_code == 403
        assert (
            await client.post(
                path, json={"enabled": True}, headers={"Authorization": "Bearer super"}
            )
        ).status_code == 200
        assert await stack.session.scalar(select(func.count()).select_from(AdminAudit)) == 1
        sid = "browser-session"
        await stack.redis.set(
            "admin:session:" + sid,
            stack.secrets.encrypt(json.dumps({"subject": "super", "csrf": "required-csrf"})),
        )
        client.cookies.set("__Host-wakeelm_admin", sid)
        assert (await client.post(path, json={"enabled": False})).status_code == 403
        assert (
            await client.post(
                path,
                json={"enabled": False},
                headers={"X-CSRF-Token": "required-csrf", "Origin": "https://evil.example"},
            )
        ).status_code == 403
        assert (
            await client.post(
                path,
                json={"enabled": False},
                headers={"X-CSRF-Token": "required-csrf", "Origin": "https://agent.example"},
            )
        ).status_code == 200
