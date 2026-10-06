import pytest
from conftest import MockHTTP

from app.core.exceptions import SafeError
from app.providers.adapters.openai import (
    NvidiaNimAdapter,
    OpenAICompatibleAdapter,
    OpenRouterAdapter,
)
from app.providers.registry import ProviderRegistry


@pytest.mark.parametrize(
    "kind,adapter",
    [
        ("OPENAI_COMPATIBLE", OpenAICompatibleAdapter),
        ("CUSTOM_OPENAI_COMPATIBLE", OpenAICompatibleAdapter),
        ("OPENROUTER", OpenRouterAdapter),
        ("NVIDIA_NIM", NvidiaNimAdapter),
    ],
)
async def test_adapters(kind, adapter):
    http = MockHTTP()
    instance = ProviderRegistry.resolve(
        kind,
        base_url="https://example.com/v1",
        token="secret",
        headers={"X-API-Key": "custom"},
        http=http,
    )
    assert isinstance(instance, adapter)
    models = await instance.discover_models()
    assert models[0].external_id == "remote/model"
    assert models[0].pricing["classification"] == "UNKNOWN"
    assert models[0].capabilities["tool_calling"]["state"] == "UNKNOWN"
    content, usage = await instance.test_model(models[0].external_id)
    assert content == "OK" and usage["completion_tokens"] == 1
    assert http.calls[-1][3]["max_tokens"] == 4
    assert http.calls[-1][2]["x-api-key"] == "custom"


async def test_fallback_paths():
    http = MockHTTP()
    original = http.request

    async def request(method, url, headers, payload=None):
        if url == "https://example.com/models":
            raise SafeError("UNSUPPORTED", 404)
        return await original(method, url, headers, payload)

    http.request = request
    adapter = OpenAICompatibleAdapter("https://example.com", "token", {}, http)
    await adapter.discover_models()
    assert adapter.api_url == "https://example.com/v1"
    await adapter.create_chat_completion("remote/model", "hi")
    assert http.calls[-1][1] == "https://example.com/v1/chat/completions"


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"data": {}},
        {"data": [{}]},
        {"data": [{"id": None}]},
        {"data": [{"id": "m"}, {"id": "m"}]},
        {"data": ["model"]},
    ],
)
async def test_invalid_model_responses(data):
    http = MockHTTP()
    http.data = data
    adapter = OpenAICompatibleAdapter("https://example.com/v1", "token", {}, http)
    with pytest.raises(SafeError, match="INVALID_RESPONSE"):
        await adapter.discover_models()


@pytest.mark.parametrize(
    "code", ["AUTH_FAILED", "RATE_LIMITED", "TIMEOUT", "OFFLINE", "INVALID_RESPONSE"]
)
async def test_error_mapping(code):
    http = MockHTTP()
    http.error = SafeError(code)
    adapter = OpenAICompatibleAdapter("https://example.com/v1", "token", {}, http)
    with pytest.raises(SafeError, match=code):
        await adapter.discover_models()


@pytest.mark.parametrize(
    "prompt,completion,classification",
    [
        ("0", "0", "FREE_REPORTED"),
        ("0.1", "0", "PAID"),
        ("-1", "0", "UNKNOWN"),
        ("NaN", "0", "UNKNOWN"),
        ("unknown", "0", "UNKNOWN"),
    ],
)
def test_openrouter_metadata(prompt, completion, classification):
    adapter = OpenRouterAdapter("https://openrouter.ai/api/v1", "token", {}, MockHTTP())
    model = adapter.normalize_model(
        {
            "id": "vendor/name:free",
            "pricing": {"prompt": prompt, "completion": completion},
            "supported_parameters": ["tools", "reasoning"],
            "architecture": {"input_modalities": ["image", "text"]},
        }
    )
    assert model.external_id == "vendor/name:free"
    assert model.pricing["classification"] == classification
    assert model.capabilities["tool_calling"]["state"] == "SUPPORTED"
    assert model.capabilities["vision"]["state"] == "SUPPORTED"


def test_registry():
    assert ProviderRegistry.detect("https://unknown.example") == "CUSTOM_OPENAI_COMPATIBLE"
    assert ProviderRegistry.detect("https://openrouter.ai/api/v1") == "OPENROUTER"
    assert ProviderRegistry.detect("https://integrate.api.nvidia.com/v1") == "NVIDIA_NIM"
    assert (
        ProviderRegistry.detect("https://openrouter.ai/api/v1", "OPENAI_COMPATIBLE")
        == "OPENAI_COMPATIBLE"
    )


async def test_no_discovery_endpoint():
    http = MockHTTP()
    http.error = SafeError("UNSUPPORTED", 404)
    adapter = OpenAICompatibleAdapter("https://example.com", "token", {}, http)
    with pytest.raises(SafeError, match="UNSUPPORTED"):
        await adapter.discover_models()


def test_openrouter_request_price_and_case_insensitive_auth():
    adapter = OpenRouterAdapter(
        "https://openrouter.ai/api/v1", "secret", {"Authorization": "Custom secret"}, MockHTTP()
    )
    model = adapter.normalize_model(
        {"id": "vendor/free-name", "pricing": {"prompt": "0", "completion": "0", "request": "0.1"}}
    )
    assert model.pricing["classification"] == "PAID"
    assert adapter.headers == {"authorization": "Custom secret"}
