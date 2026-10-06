from urllib.parse import urlsplit

from app.core.exceptions import SafeError
from app.providers.adapters.openai import (
    NvidiaNimAdapter,
    OpenAICompatibleAdapter,
    OpenRouterAdapter,
)


class ProviderRegistry:
    adapters = {
        "OPENAI_COMPATIBLE": OpenAICompatibleAdapter,
        "CUSTOM_OPENAI_COMPATIBLE": OpenAICompatibleAdapter,
        "OPENROUTER": OpenRouterAdapter,
        "NVIDIA_NIM": NvidiaNimAdapter,
    }

    @classmethod
    def detect(cls, url, explicit=None):
        if explicit:
            if explicit not in cls.adapters:
                raise SafeError("INVALID_PROVIDER")
            return explicit
        host = urlsplit(url).hostname
        return {"openrouter.ai": "OPENROUTER", "integrate.api.nvidia.com": "NVIDIA_NIM"}.get(
            host, "CUSTOM_OPENAI_COMPATIBLE"
        )

    @classmethod
    def resolve(cls, provider_type, **kwargs):
        if provider_type not in cls.adapters:
            raise SafeError("INVALID_PROVIDER")
        return cls.adapters[provider_type](provider_type=provider_type, **kwargs)
