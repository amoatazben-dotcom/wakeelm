import base64
import hashlib
import json
import secrets
from datetime import timedelta

from sqlalchemy import update

from app.agent.approvals import utc
from app.core.exceptions import SafeError
from app.db.base import now
from app.db.models.integrations import OAuthState
from app.integrations.http import origin, validate_https


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def pkce(verifier):
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")


class OAuthStateService:
    def __init__(self, session, secret_manager, settings):
        self.session, self.secrets, self.settings = session, secret_manager, settings

    def callback_base(self):
        base = self.settings.integrations_callback_base_url
        if not base or not base.startswith("https://"):
            raise SafeError("OAUTH_UNCONFIGURED")
        from app.providers.url import BaseURLResolver

        return BaseURLResolver.normalize(base)

    async def issue(self, user_id, kind, target_id, payload, nonce=None):
        state = secrets.token_urlsafe(32)
        nonce = nonce or secrets.token_urlsafe(32)
        row = OAuthState(
            id=digest(state),
            user_id=user_id,
            kind=kind,
            target_id=str(target_id),
            nonce_hash=digest(nonce),
            payload_encrypted=self.secrets.encrypt(json.dumps(payload)),
            expires_at=now() + timedelta(seconds=self.settings.oauth_state_ttl_seconds),
        )
        self.session.add(row)
        await self.session.flush()
        return state, nonce

    async def consume(self, state, nonce, kind):
        if not isinstance(state, str) or len(state) > 100 or not nonce:
            raise SafeError("OAUTH_STATE_INVALID")
        query = (
            update(OAuthState)
            .where(
                OAuthState.id == digest(state),
                OAuthState.kind == kind,
                OAuthState.nonce_hash == digest(nonce),
                OAuthState.consumed_at.is_(None),
                OAuthState.expires_at > now(),
            )
            .values(consumed_at=now())
            .returning(OAuthState)
        )
        row = await self.session.scalar(query)
        if row is None:
            raise SafeError("OAUTH_STATE_INVALID")
        await self.session.commit()
        return row, json.loads(self.secrets.decrypt(row.payload_encrypted))

    async def ticket(self, user_id, kind, target_id, payload):
        value, _ = await self.issue(user_id, kind + "_TICKET", target_id, payload, nonce="ticket")
        return self.callback_base() + f"/integrations/{kind.lower()}/connect?ticket=" + value


class MCPOAuth:
    def __init__(self, session, user_id, settings, secrets, limits, http=None):
        from app.integrations.http import IntegrationHTTP
        from app.integrations.ownership import IntegrationOwnership

        self.session, self.user_id, self.settings, self.secrets, self.limits = (
            session,
            user_id,
            settings,
            secrets,
            limits,
        )
        self.http = http or IntegrationHTTP(
            settings.mcp_connect_timeout_seconds, settings.mcp_max_response_bytes
        )
        self.owned = IntegrationOwnership(session, user_id)
        self.states = OAuthStateService(session, secrets, settings)

    async def discover(self, server):
        from urllib.parse import urlsplit

        path = urlsplit(server.server_url).path.rstrip("/")
        resource = await self.http.request(
            "GET", origin(server.server_url) + "/.well-known/oauth-protected-resource" + path
        )
        if resource.get("resource", "").rstrip("/") != server.server_url.rstrip("/"):
            raise SafeError("OAUTH_ISSUER_MISMATCH")
        issuers = resource.get("authorization_servers", [])
        if not isinstance(issuers, list) or len(issuers) != 1:
            raise SafeError("OAUTH_ISSUER_MISMATCH")
        issuer = issuers[0].rstrip("/")
        await validate_https(issuer)
        metadata = await self.http.request(
            "GET", issuer + "/.well-known/oauth-authorization-server"
        )
        if metadata.get("issuer", "").rstrip("/") != issuer or "S256" not in metadata.get(
            "code_challenge_methods_supported", []
        ):
            raise SafeError("OAUTH_ISSUER_MISMATCH")
        for key in ("authorization_endpoint", "token_endpoint"):
            await validate_https(metadata[key])
            if origin(metadata[key]) != origin(issuer):
                raise SafeError("OAUTH_ISSUER_MISMATCH")
        client_id = self.settings.mcp_oauth_clients.get(issuer)
        if not isinstance(client_id, str) or not client_id:
            raise SafeError("OAUTH_CLIENT_UNCONFIGURED")
        return {
            "issuer": issuer,
            "client_id": client_id,
            "authorization_endpoint": metadata["authorization_endpoint"],
            "token_endpoint": metadata["token_endpoint"],
            "scopes_supported": resource.get(
                "scopes_supported", metadata.get("scopes_supported", [])
            ),
            "require_iss": bool(
                metadata.get("authorization_response_iss_parameter_supported", False)
            ),
        }

    async def start(self, ident, scopes):
        server = await self.owned.server(ident, False)
        if server.status in {"DISABLED", "REMOVED"}:
            raise SafeError("NOT_FOUND")
        if (
            not isinstance(scopes, list)
            or any(not isinstance(scope, str) or len(scope) > 100 for scope in scopes)
            or len(scopes) > 20
        ):
            raise SafeError("INVALID_INPUT")
        config = await self.discover(server)
        if not set(scopes) <= set(config["scopes_supported"]):
            raise SafeError("SCOPE_REQUIRED")
        config["scopes"] = scopes
        config["server_url"] = server.server_url
        from app.services.audit_service import audit

        audit(self.session, self.user_id, "MCP_SERVER_AUTH_STARTED", "mcp_server", ident)
        return await self.states.ticket(self.user_id, "MCP", ident, config)

    async def token_request(self, url, form):
        try:
            return await self.http.request("POST", url, form=form)
        except SafeError as error:
            from app.services.audit_service import audit

            audit(
                self.session,
                self.user_id,
                "MCP_SERVER_AUTH_FAILED",
                "oauth_issuer",
                status=error.code,
            )
            await self.session.commit()
            if error.http_status in {400, 401, 403}:
                raise SafeError("AUTH_FAILED") from None
            raise

    async def exchange(self, row, payload, code, issuer=None):
        server = await self.owned.server(row.target_id, False)
        if (
            row.user_id != self.user_id
            or server.server_url != payload["server_url"]
            or server.status in {"DISABLED", "REMOVED"}
        ):
            raise SafeError("OAUTH_STATE_INVALID")
        if (
            issuer
            and issuer != payload["issuer"]
            or payload["require_iss"]
            and issuer != payload["issuer"]
        ):
            raise SafeError("OAUTH_ISSUER_MISMATCH")
        tokens = await self.token_request(
            payload["token_endpoint"],
            form={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": payload["client_id"],
                "redirect_uri": payload["redirect_uri"],
                "code_verifier": payload["verifier"],
                "resource": server.server_url,
            },
        )
        return await self.save(server, payload, tokens)

    async def save(self, server, config, tokens, existing=None):
        import uuid

        from app.db.models.integrations import MCPCredential

        token = tokens.get("access_token")
        ttl = tokens.get("expires_in", 3600)
        raw_scopes = tokens.get("scope", " ".join(config["scopes"]))
        if not isinstance(raw_scopes, str) or not isinstance(tokens.get("token_type"), str):
            raise SafeError("INVALID_RESPONSE")
        scopes = raw_scopes.split()
        if (
            not isinstance(token, str)
            or not token
            or len(token) > 10000
            or tokens.get("token_type", "").lower() != "bearer"
            or not isinstance(ttl, int)
            or not 0 < ttl <= 86400
            or not set(scopes) <= set(config["scopes"])
        ):
            from app.services.audit_service import audit

            audit(
                self.session,
                self.user_id,
                "MCP_SERVER_AUTH_FAILED",
                "mcp_server",
                server.id,
                status="OAUTH_SCOPE_ESCALATION",
            )
            await self.session.commit()
            raise SafeError("OAUTH_SCOPE_ESCALATION")
        value = existing or MCPCredential(
            id=str(uuid.uuid4()),
            user_id=self.user_id,
            mcp_server_id=server.id,
            credential_type="OAUTH",
        )
        value.encrypted_access_token = self.secrets.encrypt(token)
        refresh = tokens.get("refresh_token")
        if refresh:
            if not isinstance(refresh, str) or len(refresh) > 10000:
                raise SafeError("INVALID_RESPONSE")
            value.encrypted_refresh_token = self.secrets.encrypt(refresh)
        value.expires_at = now() + timedelta(seconds=ttl)
        value.scopes_json = scopes
        value.issuer = config["issuer"]
        value.metadata_json = {
            "client_id": config["client_id"],
            "token_endpoint": config["token_endpoint"],
            "server_url": server.server_url,
        }
        self.session.add(value)
        server.auth_type = "OAUTH"
        server.encrypted_auth_config = None
        server.status = "PENDING"
        from app.services.audit_service import audit

        audit(self.session, self.user_id, "MCP_SERVER_AUTH_COMPLETED", "mcp_server", server.id)
        await self.session.flush()
        return value

    async def credential(self, server):
        from sqlalchemy import select

        from app.db.models.integrations import MCPCredential

        value = await self.session.scalar(
            select(MCPCredential).where(
                MCPCredential.mcp_server_id == server.id, MCPCredential.user_id == self.user_id
            )
        )
        if not value:
            raise SafeError("AUTH_REQUIRED")
        if value.metadata_json.get("server_url") != server.server_url:
            raise SafeError("AUTH_ORIGIN_MISMATCH")
        if utc(value.expires_at) > now() + timedelta(seconds=30):
            return self.secrets.decrypt(value.encrypted_access_token)
        if not value.encrypted_refresh_token:
            raise SafeError("AUTH_REQUIRED")
        async with self.limits.lock("mcp:refresh:" + server.id, 60):
            await self.session.refresh(value)
            if utc(value.expires_at) > now() + timedelta(seconds=30):
                return self.secrets.decrypt(value.encrypted_access_token)
            config = {**value.metadata_json, "issuer": value.issuer, "scopes": value.scopes_json}
            tokens = await self.token_request(
                config["token_endpoint"],
                form={
                    "grant_type": "refresh_token",
                    "refresh_token": self.secrets.decrypt(value.encrypted_refresh_token),
                    "client_id": config["client_id"],
                    "scope": " ".join(value.scopes_json),
                    "resource": server.server_url,
                },
            )
            await self.save(server, config, tokens, value)
            server.status = "CONNECTED"
            from app.services.audit_service import audit

            audit(self.session, self.user_id, "MCP_TOKEN_REFRESHED", "mcp_server", server.id)
            await self.session.commit()
            return self.secrets.decrypt(value.encrypted_access_token)
