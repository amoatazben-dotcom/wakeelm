from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.core.exceptions import SafeError
from app.db.models import (
    AuditLog,
    Model,
    ModelHealthCheck,
    Provider,
    ProviderHealthCheck,
    User,
    UserSetting,
)
from app.db.repositories.owned import OwnedRepository
from app.schemas.providers import ProviderInput
from app.services.model_service import ModelService
from app.services.user_service import change_language, ensure_user


async def create(stack):
    return await stack.service.create(
        ProviderInput(
            name="Custom",
            base_url="https://example.com/v1",
            api_token="private-token-example",
            headers={"X-API-Key": "private-header"},
        )
    )


async def test_user_and_language(stack):
    user = await ensure_user(
        stack.session, SimpleNamespace(id=123, username="updated", first_name="New", last_name=None)
    )
    assert user.id == stack.user.id and user.language == "ar"
    await change_language(stack.session, user, "en")
    await stack.session.commit()
    assert await stack.session.scalar(select(func.count()).select_from(User)) == 1
    actions = list(await stack.session.scalars(select(AuditLog.action)))
    assert actions == ["USER_REGISTERED", "LANGUAGE_CHANGED"]


async def test_full_lifecycle(stack):
    provider = await create(stack)
    assert "private-token" not in provider.encrypted_api_token
    assert "private-header" not in provider.extra_headers_encrypted
    assert stack.secrets.decrypt(provider.encrypted_api_token) == "private-token-example"
    assert await stack.service.discover(provider.id) is None
    await stack.session.flush()
    models = ModelService(stack.service)
    page, total = await models.page()
    assert total == 1 and page[0].status == "UNTESTED" and not page[0].is_available
    await models.activate(page[0].id)
    await stack.session.commit()
    # Restart-like session: all selections survive a fresh DB session.
    async with stack.sessions() as fresh:
        assert (await fresh.get(Provider, provider.id)).name == "Custom"
        assert (await fresh.scalar(select(UserSetting))).value_json["active_model_id"] == page[0].id
    assert await models.chat("Hello") == "OK"
    assert await models.test(page[0].id) is None
    await stack.session.flush()
    assert page[0].status == "AVAILABLE"
    assert await stack.session.scalar(select(func.count()).select_from(ModelHealthCheck)) == 2
    await stack.service.disable(provider.id)
    await stack.session.flush()
    await stack.redis.delete(f"limit:chat:{stack.user.id}")
    with pytest.raises(SafeError, match="NO_ACTIVE_MODEL"):
        await models.chat("Hi")
    await stack.service.delete(provider.id)
    await stack.session.commit()
    assert await stack.session.get(Provider, provider.id) is None
    assert await stack.session.scalar(select(func.count()).select_from(Model)) == 0
    audit = list(await stack.session.scalars(select(AuditLog)))
    assert all("private-token" not in str(row.metadata_json) for row in audit)


@pytest.mark.parametrize("method", ["provider", "model"])
async def test_ownership(stack, method):
    provider = await create(stack)
    await stack.service.discover(provider.id)
    await stack.session.flush()
    ident = provider.id if method == "provider" else await stack.session.scalar(select(Model.id))
    other = OwnedRepository(stack.session, 999)
    with pytest.raises(SafeError, match="NOT_FOUND"):
        await getattr(other, method)(ident)


async def test_pagination_and_filters(stack):
    provider = await create(stack)
    stack.http.data = {"data": [{"id": f"model-{n}"} for n in range(23)]}
    await stack.service.discover(provider.id)
    await stack.session.flush()
    models = ModelService(stack.service)
    first, total = await models.page(0)
    second, _ = await models.page(1)
    third, _ = await models.page(2)
    assert total == 23 and [len(first), len(second), len(third)] == [10, 10, 3]
    assert not {m.id for m in first} & {m.id for m in second}
    assert (await models.page(filter="free"))[1] == 0
    assert (await models.page(filter="unknown"))[1] == 23


@pytest.mark.parametrize(
    "code,status",
    [
        ("AUTH_FAILED", "AUTH_FAILED"),
        ("RATE_LIMITED", "RATE_LIMITED"),
        ("TIMEOUT", "OFFLINE"),
        ("INVALID_RESPONSE", "INVALID_RESPONSE"),
        ("UNSUPPORTED", "DEGRADED"),
    ],
)
async def test_provider_health(stack, code, status):
    provider = await create(stack)
    stack.http.error = SafeError(code)
    error = await stack.service.discover(provider.id)
    await stack.session.flush()
    assert error.code == code and provider.status == status
    assert (await stack.session.scalar(select(ProviderHealthCheck))).error_message_safe == code


async def test_cooldown(stack):
    provider = await create(stack)
    await stack.service.discover(provider.id)
    with pytest.raises(SafeError, match="RATE_LIMITED"):
        await stack.service.discover(provider.id)


async def test_no_active_model(stack):
    await stack.redis.delete(f"limit:chat:{stack.user.id}")
    with pytest.raises(SafeError, match="NO_ACTIVE_MODEL"):
        await ModelService(stack.service).chat("hi")


async def test_audit_redaction(stack):
    from app.services.audit_service import audit

    audit(
        stack.session,
        stack.user.id,
        "PROVIDER_TESTED",
        token="secret",
        headers={"secret": "value"},
        status="ONLINE",
    )
    await stack.session.flush()
    record = await stack.session.scalar(
        select(AuditLog).where(AuditLog.action == "PROVIDER_TESTED")
    )
    assert record.metadata_json == {"status": "ONLINE"}


async def test_provider_update_resets_selection_and_tests(stack):
    provider = await create(stack)
    await stack.service.discover(provider.id)
    models = ModelService(stack.service)
    rows, _ = await models.page()
    await models.activate(rows[0].id)
    await models.test(rows[0].id)
    await stack.session.flush()
    updated = await stack.service.update(
        provider.id,
        ProviderInput(
            name="New",
            base_url="https://example.com/v1",
            api_token="new-token-example",
            headers={"api-key": "new-private-header"},
        ),
    )
    await stack.session.flush()
    assert updated.name == "New" and updated.status == "UNKNOWN"
    assert stack.secrets.decrypt(updated.encrypted_api_token) == "new-token-example"
    assert rows[0].status == "UNTESTED" and not rows[0].is_available
    assert rows[0].capabilities_json["chat"]["state"] == "UNKNOWN"
    assert await stack.session.scalar(select(UserSetting)) is None
    await stack.service.update(
        provider.id,
        ProviderInput(name="Other", base_url="https://another.example/v1", api_token="new-secret"),
    )
    await stack.session.flush()
    assert await stack.session.scalar(select(func.count()).select_from(Model)) == 0


async def test_refresh_preserves_test_evidence_and_reappearance(stack):
    provider = await create(stack)
    await stack.service.discover(provider.id)
    models = ModelService(stack.service)
    rows, _ = await models.page()
    await models.test(rows[0].id)
    await stack.redis.delete(f"limit:discover:{provider.id}")
    await stack.service.discover(provider.id)
    assert rows[0].capabilities_json["chat"]["source"] == "TESTED"
    stack.http.data = {"data": []}
    await stack.redis.delete(f"limit:discover:{provider.id}")
    await stack.service.discover(provider.id)
    assert rows[0].status == "UNSUPPORTED"
    stack.http.data = {"data": [{"id": "remote/model"}]}
    await stack.redis.delete(f"limit:discover:{provider.id}")
    await stack.service.discover(provider.id)
    assert rows[0].status == "UNTESTED" and not rows[0].is_available


async def test_active_selection_cannot_cross_owners(stack):
    from app.services.provider_service import ProviderService

    provider = await create(stack)
    await stack.service.discover(provider.id)
    await stack.session.flush()
    model_id = await stack.session.scalar(select(Model.id))
    other = ProviderService(stack.session, 999, stack.secrets, stack.http, stack.service.limits)
    with pytest.raises(SafeError, match="NOT_FOUND"):
        await ModelService(other).activate(model_id)
    with pytest.raises(SafeError, match="NOT_FOUND"):
        await ModelService(other).test(model_id)
    with pytest.raises(SafeError, match="NOT_FOUND"):
        await other.delete(provider.id)
    with pytest.raises(SafeError, match="NOT_FOUND"):
        await other.update(
            provider.id,
            ProviderInput(name="attack", base_url="https://example.com/v1", api_token="secret"),
        )
    assert await stack.session.get(Provider, provider.id) is not None


async def test_model_context_never_contains_owned_opaque_credentials(stack):
    provider = await create(stack)
    await stack.service.discover(provider.id)
    rows, _ = await ModelService(stack.service).page()
    await ModelService(stack.service).completion(
        rows[0], "Inspect private-token-example and private-header-example"
    )
    payload = stack.http.calls[-1][3]
    assert "private-token-example" not in str(payload)
    assert "private-header" not in str(payload)
    assert "[REDACTED]" in str(payload)
    assert "private-token-example" in stack.http.calls[-1][2]["authorization"]
