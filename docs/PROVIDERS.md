# Providers

Supported types: `OPENAI_COMPATIBLE`, `CUSTOM_OPENAI_COMPATIBLE`, `OPENROUTER`, `NVIDIA_NIM`. Explicit service-layer type selection wins over hostname detection. The Telegram flow detects known providers automatically and otherwise selects the custom OpenAI-compatible adapter.

Register a name, public base URL and API token. Editing repeats the encrypted onboarding flow; endpoint changes remove old models, and credential changes invalidate selection and prior test availability. Optional headers are accepted as a JSON string-to-string object; tokens and headers are encrypted. Bearer authentication is the default. `X-API-Key` and `api-key` are supported; custom `Authorization` may replace Bearer. Host/hop-by-hop/proxy framing headers are forbidden.

URLs are normalized without duplicating `/v1`. If the root ends in `/v1`, discovery tries `/models` relative to it. Otherwise it tries `/models` and then `/v1/models` only when the first endpoint returns 404. A successful API root is saved separately from the user's base URL for subsequent chat. Redirects are rejected. Missing model discovery is reported as degraded/unsupported, not successful. Manual entry is deferred.

Discovery validates `data` as a bounded list with unique, exact model IDs. Missing optional metadata is accepted; missing/invalid IDs fail safely. Only allowlisted, normalized metadata is persisted. Disappeared models are retained for health history but marked unsupported. No paid completion is made by discovery.

OpenRouter (`https://openrouter.ai/api/v1`) enriches context length, price metadata and explicitly reported capability metadata. Free is `FREE_REPORTED`, never verified merely because a request succeeded. Unknown generic and NVIDIA pricing remains `UNKNOWN`. NVIDIA (`https://integrate.api.nvidia.com/v1`, or another public NIM endpoint) uses the compatible adapter without a fixed model list. Vision/tools/reasoning are unknown unless metadata explicitly supports them; a successful test proves chat only. Coding filters are conservative and can be empty.

Model tests require a Telegram confirmation, use `Reply with OK.` and a four-token output budget; pricing may still apply. Chat is non-streaming with a 256-token output budget and no saved conversation history. POST completions are not retried to avoid duplicate charges. Users can retry after a safe localized error. Transport timeouts, authentication errors, rate limits and malformed responses are mapped to internal codes; raw provider error bodies never reach Telegram/logs.

Add an adapter by subclassing `AIProviderAdapter`, registering a type, providing metadata normalization and mocked tests. Keep provider-specific HTTP details out of handlers. Responses/embeddings/images/streaming are future extensions.
