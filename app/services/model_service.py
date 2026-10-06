import time

import structlog
from sqlalchemy import select

from app.core.exceptions import SafeError
from app.db.base import now
from app.db.models import Model, ModelHealthCheck, Provider, UserSetting
from app.services.audit_service import audit


class ModelService:
    def __init__(self, providers):
        self.providers = providers
        self.session, self.user_id, self.owned = (
            providers.session,
            providers.user_id,
            providers.owned,
        )

    async def page(self, page=0, filter="all", provider_id=None):
        if page < 0 or page > 10000:
            raise SafeError("INVALID_INPUT")
        if provider_id is not None:
            await self.owned.provider(provider_id)
        rows = list(
            await self.session.scalars(
                select(Model)
                .join(Provider)
                .where(Provider.user_id == self.user_id, Provider.status != "DISABLED")
                .order_by(Model.id)
            )
        )
        if provider_id is not None:
            rows = [m for m in rows if m.provider_id == provider_id]
        if filter == "free":
            rows = [
                m
                for m in rows
                if m.pricing_json.get("classification") in {"FREE_VERIFIED", "FREE_REPORTED"}
            ]
        elif filter == "working":
            rows = [m for m in rows if m.is_available]
        elif filter in {"tool_calling", "vision", "reasoning", "coding"}:
            rows = [
                m for m in rows if m.capabilities_json.get(filter, {}).get("state") == "SUPPORTED"
            ]
        elif filter in {"paid", "unknown"}:
            rows = [
                m
                for m in rows
                if m.pricing_json.get("classification", "UNKNOWN")
                == {"paid": "PAID", "unknown": "UNKNOWN"}[filter]
            ]
        elif filter != "all":
            raise SafeError("INVALID_INPUT")
        return rows[page * 10 : page * 10 + 10], len(rows)

    async def activate(self, model_id):
        model = await self.owned.model(model_id)
        provider = await self.owned.provider(model.provider_id)
        if provider.status == "DISABLED" or model.status == "UNSUPPORTED":
            raise SafeError("DISABLED")
        setting = await self.session.scalar(
            select(UserSetting).where(
                UserSetting.user_id == self.user_id, UserSetting.key == "active_model"
            )
        )
        if setting is None:
            setting = UserSetting(user_id=self.user_id, key="active_model")
            self.session.add(setting)
        setting.value_json = {"active_provider_id": provider.id, "active_model_id": model.id}
        audit(self.session, self.user_id, "ACTIVE_MODEL_CHANGED", "model", model.id)

    async def completion(self, model, text, test=False):
        provider = await self.owned.provider(model.provider_id)
        if provider.status == "DISABLED":
            raise SafeError("DISABLED")
        adapter = self.providers.adapter(provider)
        if provider.api_base_url:
            adapter.api_url = provider.api_base_url
        elif not provider.base_url.endswith("/v1"):
            await adapter.discover_models()
        if test:
            return await adapter.test_model(model.external_model_id)
        return await adapter.create_chat_completion(model.external_model_id, text)

    async def test(self, model_id):
        model = await self.owned.model(model_id)
        await self.providers.limits.cooldown(f"test:user:{self.user_id}", 10)
        await self.providers.limits.cooldown(f"test:model:{model.id}", 30)
        started, error = time.monotonic(), None
        try:
            await self.completion(model, "Reply with OK.", True)
            model.status, model.is_available = "AVAILABLE", True
            caps = dict(model.capabilities_json)
            caps["chat"] = {"state": "SUPPORTED", "source": "TESTED"}
            model.capabilities_json = caps
        except SafeError as exc:
            error = exc
            model.status, model.is_available = (
                exc.code
                if exc.code in {"AUTH_FAILED", "RATE_LIMITED", "UNSUPPORTED", "TIMEOUT"}
                else "FAILED",
                False,
            )
        model.last_checked_at = now()
        self.session.add(
            ModelHealthCheck(
                model_id=model.id,
                status=model.status,
                latency_ms=int((time.monotonic() - started) * 1000),
                error_code=error.code if error else None,
                error_message_safe=error.code if error else None,
            )
        )
        audit(self.session, self.user_id, "MODEL_TESTED", "model", model.id, status=model.status)
        return error

    async def chat(self, text):
        if not text or len(text) > 16000:
            raise SafeError("INVALID_INPUT")
        await self.providers.limits.cooldown(f"chat:{self.user_id}", 3)
        setting = await self.session.scalar(
            select(UserSetting).where(
                UserSetting.user_id == self.user_id, UserSetting.key == "active_model"
            )
        )
        if setting is None:
            raise SafeError("NO_ACTIVE_MODEL")
        model = await self.owned.model(setting.value_json["active_model_id"])
        if model.status == "UNSUPPORTED":
            raise SafeError("DISABLED")
        content, usage = await self.completion(model, text)
        structlog.get_logger().info(
            "chat",
            provider_id=model.provider_id,
            operation="chat",
            status="ok",
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
        )
        return content
