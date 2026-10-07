import hmac
import secrets
import time

import jwt
from fastapi import HTTPException, Request

from app.core.exceptions import SafeError
from app.db.models.platform import AdminIdentity
from app.integrations.http import IntegrationHTTP

PERMISSIONS = {
    "SUPER_ADMIN": {"read", "audit", "support", "operate", "security", "quotas"},
    "ADMIN": {"read", "audit", "support", "operate", "quotas"},
    "SUPPORT": {"read", "support"},
    "AUDITOR": {"read", "audit"},
    "READ_ONLY": {"read"},
}
JWKS_CACHE = {}


async def verify_identity(token, settings, nonce=None, http=None):
    if not settings.admin_oidc_issuer:
        raise HTTPException(503, "Admin authentication is not configured")
    try:
        header = jwt.get_unverified_header(token)
        if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
            raise ValueError()
        cache = JWKS_CACHE.get(settings.admin_oidc_jwks_url)
        if not cache or cache[0] < time.monotonic():
            data = await (http or IntegrationHTTP(timeout=10, limit=100000)).request(
                "GET", settings.admin_oidc_jwks_url
            )
            keys = data["keys"]
            if not isinstance(keys, list) or len(keys) > 20:
                raise ValueError()
            JWKS_CACHE[settings.admin_oidc_jwks_url] = (time.monotonic() + 300, keys)
        else:
            keys = cache[1]
        key = next(
            k
            for k in keys
            if k.get("kid") == header["kid"]
            and k.get("kty") == "RSA"
            and k.get("use", "sig") == "sig"
        )
        claims = jwt.decode(
            token,
            jwt.PyJWK.from_dict(key).key,
            algorithms=["RS256"],
            audience=settings.admin_oidc_client_id if nonce else settings.admin_oidc_audience,
            issuer=settings.admin_oidc_issuer,
            options={"require": ["exp", "iat", "sub", "iss", "aud"]},
        )
        if not isinstance(claims["sub"], str) or len(claims["sub"]) > 255:
            raise ValueError()
        if nonce and not hmac.compare_digest(claims.get("nonce", ""), nonce):
            raise ValueError()
        if settings.admin_require_mfa and not {"mfa", "otp", "hwk"}.intersection(
            claims.get("amr", [])
        ):
            raise ValueError()
        return claims["sub"]
    except (jwt.PyJWTError, ValueError, TypeError, KeyError, StopIteration, SafeError):
        raise HTTPException(401, "Invalid admin identity") from None


async def admin(request: Request, permission="read"):
    state = request.app.state
    await state.limits.window(
        "admin:" + (request.client.host if request.client else "unknown"), 120
    )
    bearer = request.headers.get("Authorization", "")
    if bearer.startswith("Bearer "):
        subject = await verify_identity(bearer[7:], state.settings)
    else:
        sid = request.cookies.get("__Host-wakeelm_admin", "")
        if not sid or len(sid) > 100:
            raise HTTPException(401)
        encrypted = await state.redis.get("admin:session:" + sid)
        if not encrypted:
            raise HTTPException(401)
        import json

        data = json.loads(state.secrets.decrypt(encrypted.decode()))
        subject = data["subject"]
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            csrf = request.headers.get("X-CSRF-Token", "")
            if not csrf or not hmac.compare_digest(csrf, data["csrf"]):
                raise HTTPException(403, "CSRF verification failed")
            expected = state.settings.public_base_url.rstrip("/")
            if request.headers.get("Origin") != expected:
                raise HTTPException(403, "Invalid origin")
    async with state.sessions() as session:
        identity = await session.get(AdminIdentity, subject)
        if identity:
            role = identity.role if identity.enabled else "DISABLED"
        else:
            role = "SUPER_ADMIN" if subject in state.settings.admin_super_subjects else "DISABLED"
    if permission not in PERMISSIONS.get(role, set()):
        raise HTTPException(403)
    return subject, role


def session_id():
    return secrets.token_urlsafe(32)
