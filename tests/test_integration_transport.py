import asyncio
import json
import ssl
from datetime import datetime, timedelta, timezone

import pytest
from aiohttp import web
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from app.core.exceptions import SafeError
from app.integrations.http import IntegrationHTTP, PinnedHTTPTransport
from app.integrations.sanitizer import ExternalToolOutputSanitizer
from app.providers.http import PinnedResolver


@pytest.fixture
async def tls_server(tmp_path, monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "public.test")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc) - timedelta(minutes=1))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(hours=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("public.test")]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    pem = tmp_path / "cert.pem"
    pem.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    secret = tmp_path / "key.pem"
    secret.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(pem, secret)
    monkeypatch.setenv("SSL_CERT_FILE", str(pem))
    monkeypatch.setattr(
        "aiohttp.connector._SSL_CONTEXT_VERIFIED", ssl.create_default_context(cafile=str(pem))
    )

    async def validate(url):
        assert url.startswith("https://public.test:")
        return url

    async def resolve(self, host, port=0, family=0):
        return [
            {
                "hostname": host,
                "host": "127.0.0.1",
                "port": port,
                "family": 2,
                "proto": 0,
                "flags": 0,
            }
        ]

    monkeypatch.setattr("app.integrations.http.validate_https", validate)
    monkeypatch.setattr(PinnedResolver, "resolve", resolve)

    async def handle(request):
        if request.path == "/redirect":
            raise web.HTTPFound("https://169.254.169.254/metadata")
        if request.path == "/large":
            return web.Response(body=b"x" * 2048)
        if request.path == "/slow":
            await asyncio.sleep(0.1)
        return web.json_response({"ok": True})

    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0, ssl_context=context)
    await site.start()
    yield "https://public.test:" + str(site._server.sockets[0].getsockname()[1])
    await runner.cleanup()


async def test_real_tls_transport_redirect_limits_timeout_and_origin(tls_server):
    assert await IntegrationHTTP().request("GET", tls_server + "/ok") == {"ok": True}
    with pytest.raises(SafeError, match="REDIRECT_DENIED"):
        await IntegrationHTTP().request("GET", tls_server + "/redirect")
    with pytest.raises(SafeError, match="RESPONSE_TOO_LARGE"):
        await IntegrationHTTP(limit=100).request("GET", tls_server + "/large")
    with pytest.raises(SafeError, match="TIMEOUT"):
        await IntegrationHTTP(timeout=0.01).request("GET", tls_server + "/slow")
    with pytest.raises(SafeError, match="AUTH_ORIGIN_MISMATCH"):
        await IntegrationHTTP(
            transport=PinnedHTTPTransport(allowed_origin="https://different.test")
        ).request("GET", tls_server + "/ok")


def test_structured_secret_redaction_and_size():
    clean = ExternalToolOutputSanitizer(1000, ["environment-secret"])
    value = json.loads(
        clean.clean(
            {
                "password": "abcd1234",
                "nested": {"refresh_token": "secret"},
                "text": "environment-secret",
            }
        )
    )
    assert value == {
        "password": "[REDACTED]",
        "nested": {"refresh_token": "[REDACTED]"},
        "text": "[REDACTED]",
    }
    with pytest.raises(SafeError, match="RESPONSE_TOO_LARGE"):
        clean.clean("x" * 1001)
