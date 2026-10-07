import hashlib
import hmac
import json
from urllib.parse import parse_qs, urlsplit

import httpx
from fastapi import FastAPI
from pydantic import SecretStr
from test_github_stage5 import settings, stack_repo

from app.api.integrations import router
from app.core.limits import Limits
from app.integrations.oauth import OAuthStateService


def application(stack, cfg):
    app = FastAPI()
    app.include_router(router)
    app.state.settings, app.state.sessions = cfg, stack.sessions
    app.state.secrets, app.state.limits = stack.secrets, Limits(stack.redis)
    return app


async def test_https_connect_cookie_state_pkce_and_replay(stack, tmp_path):
    cfg = settings(
        tmp_path, github_app_id=1, github_client_id="client", github_client_secret="secret"
    )
    states = OAuthStateService(stack.session, stack.secrets, cfg)
    url = await states.ticket(stack.user.id, "GITHUB", "11", {"installation_id": 11})
    await stack.session.commit()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application(stack, cfg)),
        base_url="https://bot.example.test",
    ) as client:
        response = await client.get(url)
        assert response.status_code == 302
        query = parse_qs(urlsplit(response.headers["location"]).query)
        assert query["code_challenge_method"] == ["S256"] and len(query["code_challenge"][0]) == 43
        assert (
            "Secure" in response.headers["set-cookie"]
            and "HttpOnly" in response.headers["set-cookie"]
        )
        assert response.headers["cache-control"] == "no-store"
        assert (await client.get(url)).status_code == 400
        assert (await client.get("/integrations/github/callback?code=fake&state=wrong")).json()[
            "error"
        ] == "OAUTH_STATE_INVALID"


async def test_signed_webhook_revocation_idempotency_and_invalid_signature(
    stack, tmp_path, monkeypatch
):
    s = await stack_repo(stack, tmp_path, monkeypatch)
    s.connection.connection_type = "APP"
    s.connection.installation_id = 11
    await stack.session.commit()
    s.w.settings.github_webhook_secret = SecretStr("webhook-test-secret")
    app = application(stack, s.w.settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://bot.example.test"
    ) as client:
        body = json.dumps({"installation": {"id": 11}, "action": "deleted"}).encode()
        headers = {"X-GitHub-Delivery": "delivery-1", "X-GitHub-Event": "installation"}
        assert (
            await client.post("/webhooks/github", content=body, headers=headers)
        ).status_code == 403
        headers["X-Hub-Signature-256"] = (
            "sha256=" + hmac.new(b"webhook-test-secret", body, hashlib.sha256).hexdigest()
        )
        assert (await client.post("/webhooks/github", content=body, headers=headers)).json() == {
            "ok": True
        }
        assert (await client.post("/webhooks/github", content=body, headers=headers)).json()[
            "duplicate"
        ]
        await stack.session.refresh(s.connection)
        await stack.session.refresh(s.repo)
        assert s.connection.status == "REVOKED" and s.repo.is_disabled
        headers.update({"X-GitHub-Delivery": "delivery-2", "X-GitHub-Event": "unknown"})
        assert (await client.post("/webhooks/github", content=body, headers=headers)).json()[
            "ignored"
        ]
        assert (await client.post("/webhooks/github", content=body, headers=headers)).json()[
            "duplicate"
        ]
