import json
import time

from sqlalchemy import delete, select

from app.core.exceptions import SafeError
from app.core.security import token_hint
from app.db.base import now
from app.db.models import Model, Provider, ProviderHealthCheck, UserSetting
from app.db.repositories.owned import OwnedRepository
from app.providers.registry import ProviderRegistry
from app.providers.url import public_addresses
from app.services.audit_service import audit


class ProviderService:
    def __init__(self, session, user_id, secrets, http, limits, max_models=1000):
        self.session, self.user_id = session, user_id
        self.secrets, self.http, self.limits, self.max_models = secrets, http, limits, max_models
        self.owned = OwnedRepository(session, user_id)

    async def create(self, data):
        await public_addresses(data.base_url)
        token = data.api_token.get_secret_value()
        provider = Provider(
            user_id=self.user_id,
            name=data.name,
            base_url=data.base_url,
            provider_type=ProviderRegistry.detect(data.base_url, data.provider_type),
            encrypted_api_token=self.secrets.encrypt(token),
            token_hint=token_hint(token),
            extra_headers_encrypted=self.secrets.encrypt_headers(data.headers),
        )
        self.session.add(provider)
        await self.session.flush()
        audit(self.session, self.user_id, "PROVIDER_CREATED", "provider", provider.id)
        return provider

    async def update(self, provider_id, data):
        provider = await self.owned.provider(provider_id, for_update=True)
        await public_addresses(data.base_url)
        kind = ProviderRegistry.detect(data.base_url, data.provider_type)
        await self.invalidate(provider.id)
        if provider.base_url != data.base_url or provider.provider_type != kind:
            await self.session.execute(delete(Model).where(Model.provider_id == provider.id))
        else:
            for model in await self.session.scalars(
                select(Model).where(Model.provider_id == provider.id)
            ):
                model.status, model.is_available, model.last_checked_at = "UNTESTED", False, None
                caps = dict(model.capabilities_json)
                for key, value in caps.items():
                    if value.get("source") == "TESTED":
                        caps[key] = {"state": "UNKNOWN", "source": "NOT_TESTED"}
                model.capabilities_json = caps
        token = data.api_token.get_secret_value()
        provider.name, provider.base_url, provider.provider_type = data.name, data.base_url, kind
        provider.encrypted_api_token = self.secrets.encrypt(token)
        provider.extra_headers_encrypted = self.secrets.encrypt_headers(data.headers)
        provider.token_hint = token_hint(token)
        provider.api_base_url, provider.status, provider.last_checked_at = None, "UNKNOWN", None
        audit(self.session, self.user_id, "PROVIDER_UPDATED", "provider", provider.id)
        return provider

    def adapter(self, provider):
        adapter = ProviderRegistry.resolve(
            provider.provider_type,
            base_url=provider.base_url,
            token=self.secrets.decrypt(provider.encrypted_api_token),
            headers=json.loads(self.secrets.decrypt(provider.extra_headers_encrypted)),
            http=self.http,
            max_models=self.max_models,
        )
        return adapter

    async def list(self):
        return list(
            await self.session.scalars(
                select(Provider).where(Provider.user_id == self.user_id).order_by(Provider.id)
            )
        )

    async def discover(self, provider_id):
        provider = await self.owned.provider(provider_id, for_update=True)
        if provider.status == "DISABLED":
            raise SafeError("DISABLED")
        await self.limits.cooldown(f"discover:{provider.id}", 15)
        started = time.monotonic()
        error = None
        async with self.limits.lock(f"provider:{provider.id}"):
            try:
                adapter = self.adapter(provider)
                models = await adapter.discover_models()
                provider.api_base_url = adapter.api_url
                known = {
                    m.external_model_id: m
                    for m in await self.session.scalars(
                        select(Model).where(Model.provider_id == provider.id)
                    )
                }
                present = {m.external_id for m in models}
                for item in models:
                    model = known.get(item.external_id)
                    if model is None:
                        model = Model(provider_id=provider.id, external_model_id=item.external_id)
                        self.session.add(model)
                    if model.id is not None:
                        for key, value in model.capabilities_json.items():
                            if value.get("source") == "TESTED":
                                item.capabilities[key] = value
                        if model.status == "UNSUPPORTED":
                            model.status, model.is_available = "UNTESTED", False
                    (
                        model.display_name,
                        model.capabilities_json,
                        model.pricing_json,
                        model.metadata_json,
                    ) = item.display_name, item.capabilities, item.pricing, item.metadata
                for ident, model in known.items():
                    if ident not in present:
                        model.is_available, model.status = False, "UNSUPPORTED"
                provider.status = "ONLINE"
                audit(
                    self.session,
                    self.user_id,
                    "MODELS_DISCOVERED",
                    "provider",
                    provider.id,
                    count=len(models),
                )
            except SafeError as exc:
                error = exc
                provider.status = (
                    "DEGRADED"
                    if exc.code == "UNSUPPORTED"
                    else ("OFFLINE" if exc.code == "TIMEOUT" else exc.code)
                )
            provider.last_checked_at = now()
            self.session.add(
                ProviderHealthCheck(
                    provider_id=provider.id,
                    status=provider.status,
                    http_status=error.http_status if error else 200,
                    latency_ms=int((time.monotonic() - started) * 1000),
                    error_code=error.code if error else None,
                    error_message_safe=error.code if error else None,
                )
            )
            audit(
                self.session,
                self.user_id,
                "PROVIDER_TESTED",
                "provider",
                provider.id,
                status=provider.status,
            )
        return error

    async def invalidate(self, provider_id):
        setting = await self.session.scalar(
            select(UserSetting).where(
                UserSetting.user_id == self.user_id, UserSetting.key == "active_model"
            )
        )
        if setting and setting.value_json.get("active_provider_id") == provider_id:
            await self.session.delete(setting)

    async def disable(self, provider_id):
        provider = await self.owned.provider(provider_id, for_update=True)
        provider.status = "DISABLED"
        await self.invalidate(provider.id)
        audit(
            self.session,
            self.user_id,
            "PROVIDER_UPDATED",
            "provider",
            provider.id,
            status="DISABLED",
        )

    async def delete(self, provider_id):
        provider = await self.owned.provider(provider_id, for_update=True)
        await self.invalidate(provider.id)
        await self.session.execute(delete(Model).where(Model.provider_id == provider.id))
        await self.session.delete(provider)
        audit(self.session, self.user_id, "PROVIDER_DELETED", "provider", provider.id)

    async def rename(self, provider_id, name):
        if not 1 <= len(name.strip()) <= 100:
            raise SafeError("INVALID_INPUT")
        provider = await self.owned.provider(provider_id, for_update=True)
        provider.name = name.strip()
        audit(self.session, self.user_id, "PROVIDER_UPDATED", "provider", provider.id)
