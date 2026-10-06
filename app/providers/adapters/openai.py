from decimal import Decimal, InvalidOperation

from app.core.exceptions import SafeError
from app.providers.base import AIProviderAdapter
from app.providers.url import BaseURLResolver
from app.schemas.models import NormalizedModel


class OpenAICompatibleAdapter(AIProviderAdapter):
    def __init__(
        self, base_url, token, headers, http, max_models=1000, provider_type="OPENAI_COMPATIBLE"
    ):
        self.base_url = BaseURLResolver.normalize(base_url)
        self.headers = {
            "authorization": "Bearer " + token,
            **{k.lower(): v for k, v in headers.items()},
        }
        self.http, self.max_models, self.provider_type = http, max_models, provider_type
        self.api_url = self.base_url

    def normalize_model(self, item):
        ident = item.get("id")
        if not isinstance(ident, str) or not ident or len(ident) > 512:
            raise SafeError("INVALID_RESPONSE")
        name = item.get("name")
        model = NormalizedModel(
            external_id=ident,
            display_name=name[:512] if isinstance(name, str) else ident,
            provider=self.provider_type,
        )
        context = item.get("context_length")
        if isinstance(context, int) and not isinstance(context, bool) and context > 0:
            model.context_length = context
            model.metadata["context_length"] = context
        return model

    async def discover_models(self):
        for endpoint in BaseURLResolver.discovery_paths(self.base_url):
            try:
                response = await self.http.request("GET", endpoint, self.headers)
            except SafeError as error:
                if error.code == "UNSUPPORTED":
                    continue
                raise
            data = response.get("data")
            if (
                not isinstance(data, list)
                or len(data) > self.max_models
                or any(not isinstance(item, dict) for item in data)
            ):
                raise SafeError("INVALID_RESPONSE")
            models = [self.normalize_model(item) for item in data]
            if len({m.external_id for m in models}) != len(models):
                raise SafeError("INVALID_RESPONSE")
            self.api_url = endpoint.removesuffix("/models")
            return models
        raise SafeError("UNSUPPORTED")

    async def create_chat_completion(self, model, text, max_tokens=256):
        response = await self.http.request(
            "POST",
            self.api_url + "/chat/completions",
            self.headers,
            {
                "model": model,
                "messages": [{"role": "user", "content": text}],
                "max_tokens": max_tokens,
                "stream": False,
            },
        )
        try:
            content = response["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content:
                raise ValueError()
            usage = response.get("usage", {})
            safe_usage = (
                {
                    k: v
                    for k, v in usage.items()
                    if k in {"prompt_tokens", "completion_tokens"} and isinstance(v, int) and v >= 0
                }
                if isinstance(usage, dict)
                else {}
            )
            return content, safe_usage
        except (KeyError, IndexError, TypeError, ValueError):
            raise SafeError("INVALID_RESPONSE") from None


class OpenRouterAdapter(OpenAICompatibleAdapter):
    def normalize_model(self, item):
        model = super().normalize_model(item)
        price = item.get("pricing")
        if isinstance(price, dict):
            try:
                values = {k: Decimal(str(price[k])) for k in ("prompt", "completion")}
                for key in (
                    "request",
                    "image",
                    "web_search",
                    "internal_reasoning",
                    "input_cache_read",
                    "input_cache_write",
                    "audio",
                ):
                    if key in price:
                        values[key] = Decimal(str(price[key]))
                if all(v.is_finite() and v >= 0 for v in values.values()):
                    model.pricing = {
                        "classification": "FREE_REPORTED"
                        if all(v == 0 for v in values.values())
                        else "PAID",
                        **{k: str(v) for k, v in values.items()},
                        "source": "PROVIDER_METADATA",
                    }
            except (KeyError, InvalidOperation):
                pass
        parameters = item.get("supported_parameters", [])
        if isinstance(parameters, list):
            for key, remote in [
                ("tool_calling", "tools"),
                ("structured_output", "response_format"),
                ("reasoning", "reasoning"),
            ]:
                if remote in parameters:
                    model.capabilities[key] = {"state": "SUPPORTED", "source": "PROVIDER_METADATA"}
        architecture = item.get("architecture", {})
        if (
            isinstance(architecture, dict)
            and isinstance(architecture.get("input_modalities"), list)
            and "image" in architecture["input_modalities"]
        ):
            model.capabilities["vision"] = {"state": "SUPPORTED", "source": "PROVIDER_METADATA"}
        return model


class NvidiaNimAdapter(OpenAICompatibleAdapter):
    pass
