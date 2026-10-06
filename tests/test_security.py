import logging
import socket

import pytest
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import Settings
from app.core.exceptions import SafeError
from app.core.i18n import LOCALES, tr
from app.core.logging import configure_logging
from app.core.security import SecretManager, token_hint
from app.providers.url import BaseURLResolver, public_addresses
from app.schemas.providers import ProviderInput


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("https://example.com/", "https://example.com"),
        ("https://example.com/v1/", "https://example.com/v1"),
        ("https://example.com/api/v1", "https://example.com/api/v1"),
    ],
)
def test_urls(raw, expected):
    assert BaseURLResolver.normalize(raw) == expected
    assert all("/v1/v1" not in x for x in BaseURLResolver.discovery_paths(expected))


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com",
        "https://u:p@example.com",
        "https://example.com?token=secret",
        "https://example.com#fragment",
        "https://example.com:99999",
        "https://example.com/../metadata",
        "https://ex ample.com",
    ],
)
def test_invalid_urls(url):
    with pytest.raises(SafeError):
        BaseURLResolver.normalize(url)


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",
        "10.1.2.3",
        "172.16.0.1",
        "192.168.1.1",
        "169.254.169.254",
        "::1",
        "fc00::1",
        "::ffff:127.0.0.1",
        "100.64.0.1",
        "0.0.0.0",
    ],
)
async def test_ssrf_addresses(ip, monkeypatch):
    async def resolve(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]

    import asyncio

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    with pytest.raises(SafeError):
        await public_addresses("https://public.example")


@pytest.mark.parametrize(
    "host", ["localhost", "test.localhost", "api.railway.internal", "service.internal"]
)
async def test_blocked_hosts(host):
    with pytest.raises(SafeError):
        await public_addresses("http://" + host)


async def test_dns_mixed_and_rebinding(monkeypatch):
    import asyncio

    from app.providers.http import PinnedResolver

    calls = 0

    async def resolve(*args, **kwargs):
        nonlocal calls
        calls += 1
        ip = "8.8.8.8" if calls == 1 else "127.0.0.1"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    assert await public_addresses("https://example.com") == {"8.8.8.8"}
    with pytest.raises(SafeError):
        await PinnedResolver().resolve("example.com", 443)


def test_secrets():
    secret = SecretManager(Fernet.generate_key().decode())
    encoded = secret.encrypt("token-production-example")
    assert "token-production-example" not in encoded
    assert secret.decrypt(encoded) == "token-production-example"
    assert "token-production-example" not in token_hint("token-production-example")
    with pytest.raises(InvalidToken):
        SecretManager(Fernet.generate_key().decode()).decrypt(encoded)


def test_config(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:dummy")
    monkeypatch.setenv("DATABASE_URL", "postgres://localhost/agent")
    monkeypatch.setenv("REDIS_URL", "redis://localhost")
    monkeypatch.setenv("MASTER_ENCRYPTION_KEY", Fernet.generate_key().decode())
    settings = Settings(_env_file=None)
    assert settings.bot_default_language == "ar"
    assert settings.async_database_url.startswith("postgresql+asyncpg://")
    assert "dummy" not in repr(settings)
    with pytest.raises(ValueError):
        Settings(bot_mode="webhook", _env_file=None)


def test_localization():
    assert LOCALES["ar"].keys() == LOCALES["en"].keys()
    assert "مرحبًا" in tr("ar", "bot.start.title")
    assert "Welcome" in tr("en", "bot.start.title")
    assert tr("invalid", "common.saved") == tr("ar", "common.saved")


def test_safe_logs(caplog):
    import structlog

    configure_logging()
    with caplog.at_level(logging.INFO):
        structlog.get_logger().info(
            "provider_checked",
            authorization="secret-123",
            api_token="secret-123",
            encrypted_api_token="secret-123",
            private_headers={"secret": "secret-123"},
            provider_id=1,
        )
    assert "secret-123" not in caplog.text
    assert "provider_checked" in caplog.text


@pytest.mark.parametrize(
    "headers",
    [
        {"Host": "evil.example"},
        {"X-API-Key": "a\nb"},
        {"Proxy-Authorization": "secret"},
        {"Transfer-Encoding": "chunked"},
    ],
)
def test_headers(headers):
    with pytest.raises(ValueError):
        ProviderInput(
            name="test", base_url="https://example.com", api_token="secret", headers=headers
        )
